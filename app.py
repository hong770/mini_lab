import asyncio
import time

from contextlib import asynccontextmanager
from pathlib import Path


from fastapi import (
    FastAPI,
    Request
)

from fastapi.staticfiles import (
    StaticFiles
)

from fastapi.templating import (
    Jinja2Templates
)


from snmp import (
    get_basic_info,
    get_interface_snapshot
)


from database import (
    init_db,

    save_interface_history,
    get_interface_history,

    save_event,
    get_recent_events,

    create_alert,
    resolve_interface_alert,
    get_active_alerts,
    get_recent_alerts,

    cleanup_old_data,
    get_database_status
)


from alert_rules import (
    get_interface_alert_rule,
    get_all_alert_rules
)


# ============================================================
# Paths
# ============================================================

BASE_DIR = Path(
    __file__
).resolve().parent


TEMPLATE_DIR = (
    BASE_DIR
    /
    "templates"
)


STATIC_DIR = (
    BASE_DIR
    /
    "static"
)


# ============================================================
# Poll Settings
# ============================================================

# Switch 每 5 秒 Poll 一次
POLL_SECONDS = 5


# Traffic History 每 30 秒寫 SQLite
HISTORY_SAVE_SECONDS = 30


# 每小時清理一次舊資料
DATABASE_CLEANUP_SECONDS = 3600


# ============================================================
# RAM Current State
#
# Dashboard 的 /api/monitor
# 主要讀這裡。
#
# 不會每次瀏覽器 Refresh 都重新 SNMP。
# ============================================================

monitor_state = {

    "switch": {
        "online": False,

        "hostname": "Unknown",

        "ip": "192.168.10.2",

        "uptime": None,

        "cpu": None
    },

    "interfaces": [],

    "events": [],

    "alerts": [],

    "last_update": None,

    "last_error": None
}


# ============================================================
# Counter Difference
# ============================================================

def calculate_counter_diff(
    current,
    previous,
    counter_bits
):

    diff = (
        current
        -
        previous
    )


    # Counter rollover
    #
    # 例如 32-bit counter：
    #
    # 4294967295
    # ↓
    # 0
    #
    # current - previous 會變負數。
    if diff < 0:

        max_counter = (
            2 ** counter_bits
        )


        diff = (
            current
            +
            max_counter
            -
            previous
        )


    return diff


# ============================================================
# 第一次啟動時同步 Alert 狀態
#
# 這很重要。
#
# 假設程式關機期間：
#
# Gi1/0/10 DOWN
#
# 程式重新啟動時 previous_interfaces 是空的，
# 沒有 UP -> DOWN Transition。
#
# 如果完全只靠 Transition，
# 就會漏掉這個問題。
#
# 所以第一次 Poll：
#
# Current State
# ↓
# Alert DB reconciliation
# ============================================================

async def reconcile_initial_alerts(
    current_interfaces,
    current_time
):

    for current in current_interfaces.values():

        rule = (
            get_interface_alert_rule(
                current["name"]
            )
        )


        if not rule["enabled"]:
            continue


        admin_status = (
            current["admin_status"]
        )


        oper_status = (
            current["oper_status"]
        )


        # ====================================================
        # Admin UP + Oper DOWN
        #
        # 對有 Alert Rule 的 Port 來說：
        # 這代表目前有 Link 問題。
        # ====================================================

        if (
            admin_status == "UP"
            and
            oper_status == "DOWN"
        ):

            created = (
                await asyncio.to_thread(
                    create_alert,

                    current_time,

                    current["index"],

                    current["name"],

                    "INTERFACE_DOWN",

                    rule["severity"],

                    rule["description"]
                )
            )


            if created:

                print(
                    "ALERT INITIALIZED:",
                    rule["severity"],
                    current["name"],
                    "INTERFACE_DOWN"
                )


        # ====================================================
        # Port 已經正常
        #
        # 如果 DB 裡還有上一次留下來的 Active Alert，
        # 重新啟動時直接 Resolve。
        # ====================================================

        else:

            resolved = (
                await asyncio.to_thread(
                    resolve_interface_alert,

                    current_time,

                    current["index"],

                    "INTERFACE_DOWN"
                )
            )


            if resolved:

                print(
                    "ALERT RECONCILED:",
                    current["name"],
                    "resolved"
                )


# ============================================================
# Event + Alert Detector
# ============================================================

async def detect_interface_events(
    previous_interfaces,
    current_interfaces,
    current_time
):

    # 第一次 Poll 沒 previous
    if not previous_interfaces:
        return


    for (
        index,
        current
    ) in current_interfaces.items():


        # 上一次沒有這個 Interface
        if index not in previous_interfaces:
            continue


        previous = (
            previous_interfaces[
                index
            ]
        )


        previous_admin = (
            previous[
                "admin_status"
            ]
        )


        current_admin = (
            current[
                "admin_status"
            ]
        )


        previous_oper = (
            previous[
                "oper_status"
            ]
        )


        current_oper = (
            current[
                "oper_status"
            ]
        )


        # ====================================================
        # 判斷 Event Type
        # ====================================================

        event_type = None


        # Admin 狀態改變
        if (
            previous_admin
            !=
            current_admin
        ):

            if (
                previous_admin == "UP"
                and
                current_admin == "DOWN"
            ):

                event_type = (
                    "ADMIN_DOWN"
                )


            elif (
                previous_admin == "DOWN"
                and
                current_admin == "UP"
            ):

                event_type = (
                    "ADMIN_UP"
                )


            else:

                event_type = (
                    "ADMIN_CHANGE"
                )


        # Oper 狀態改變
        elif (
            previous_oper
            !=
            current_oper
        ):

            if (
                previous_oper == "UP"
                and
                current_oper == "DOWN"
            ):

                # Admin 還是 UP
                #
                # 才是真的 Link Down。
                if current_admin == "UP":

                    event_type = (
                        "LINK_DOWN"
                    )

                else:

                    event_type = (
                        "LINK_CHANGE"
                    )


            elif (
                previous_oper == "DOWN"
                and
                current_oper == "UP"
            ):

                event_type = (
                    "LINK_UP"
                )


            else:

                event_type = (
                    "LINK_CHANGE"
                )


        # 完全沒變
        if event_type is None:
            continue


        # ====================================================
        # Event 裡記錄完整狀態
        # ====================================================

        old_status = (
            f"ADMIN={previous_admin}, "
            f"OPER={previous_oper}"
        )


        new_status = (
            f"ADMIN={current_admin}, "
            f"OPER={current_oper}"
        )


        # ====================================================
        # Save Event
        # ====================================================

        await asyncio.to_thread(
            save_event,

            current_time,

            current["index"],

            current["name"],

            event_type,

            old_status,

            new_status
        )


        print(
            "EVENT:",
            current["name"],
            old_status,
            "->",
            new_status,
            event_type
        )


        # ====================================================
        # Alert Rule
        # ====================================================

        rule = (
            get_interface_alert_rule(
                current["name"]
            )
        )


        # 沒啟用 Alert
        if not rule["enabled"]:
            continue


        # ====================================================
        # Link DOWN
        #
        # 建立 Active Alert
        # ====================================================

        if event_type == "LINK_DOWN":

            created = (
                await asyncio.to_thread(
                    create_alert,

                    current_time,

                    current["index"],

                    current["name"],

                    "INTERFACE_DOWN",

                    rule["severity"],

                    rule["description"]
                )
            )


            if created:

                print(
                    "ALERT CREATED:",
                    rule["severity"],
                    current["name"],
                    "INTERFACE_DOWN"
                )


        # ====================================================
        # Link UP
        #
        # Resolve Alert
        # ====================================================

        elif event_type == "LINK_UP":

            resolved = (
                await asyncio.to_thread(
                    resolve_interface_alert,

                    current_time,

                    current["index"],

                    "INTERFACE_DOWN"
                )
            )


            if resolved:

                print(
                    "ALERT RESOLVED:",
                    current["name"]
                )


        # ====================================================
        # Admin DOWN
        #
        # 如果管理員自己 shutdown，
        # 不應繼續把它視為 Link Fault。
        # ====================================================

        elif event_type == "ADMIN_DOWN":

            resolved = (
                await asyncio.to_thread(
                    resolve_interface_alert,

                    current_time,

                    current["index"],

                    "INTERFACE_DOWN"
                )
            )


            if resolved:

                print(
                    "ALERT RESOLVED BY ADMIN DOWN:",
                    current["name"]
                )


        # ====================================================
        # Admin UP
        #
        # 如果 no shutdown 後，
        # Port 仍然沒有 Link，
        # 直接建立 Alert。
        # ====================================================

        elif event_type == "ADMIN_UP":

            if current_oper == "DOWN":

                created = (
                    await asyncio.to_thread(
                        create_alert,

                        current_time,

                        current["index"],

                        current["name"],

                        "INTERFACE_DOWN",

                        rule["severity"],

                        rule["description"]
                    )
                )


                if created:

                    print(
                        "ALERT CREATED AFTER ADMIN UP:",
                        rule["severity"],
                        current["name"]
                    )


# ============================================================
# SNMP Background Poller
# ============================================================

async def poll_switch():

    previous_interfaces = {}

    previous_time = None

    last_history_save = 0

    first_poll = True


    while True:

        try:

            # =================================================
            # SNMP
            # =================================================

            basic_info = (
                await asyncio.to_thread(
                    get_basic_info
                )
            )


            current_interfaces = (
                await asyncio.to_thread(
                    get_interface_snapshot
                )
            )


            current_time = (
                time.time()
            )


            # =================================================
            # First Poll Alert Reconciliation
            # =================================================

            if first_poll:

                await reconcile_initial_alerts(
                    current_interfaces,
                    current_time
                )

                first_poll = False


            # =================================================
            # Event / Alert Detection
            # =================================================

            else:

                await detect_interface_events(
                    previous_interfaces,
                    current_interfaces,
                    current_time
                )


            # =================================================
            # Traffic Calculation
            # =================================================

            interfaces = []


            for (
                index,
                current
            ) in current_interfaces.items():


                rx_mbps = 0.0

                tx_mbps = 0.0


                if (
                    previous_time is not None
                    and
                    index in previous_interfaces
                ):

                    elapsed = (
                        current_time
                        -
                        previous_time
                    )


                    previous = (
                        previous_interfaces[
                            index
                        ]
                    )


                    rx_diff = (
                        calculate_counter_diff(
                            current[
                                "rx_counter"
                            ],

                            previous[
                                "rx_counter"
                            ],

                            current[
                                "counter_bits"
                            ]
                        )
                    )


                    tx_diff = (
                        calculate_counter_diff(
                            current[
                                "tx_counter"
                            ],

                            previous[
                                "tx_counter"
                            ],

                            current[
                                "counter_bits"
                            ]
                        )
                    )


                    if elapsed > 0:

                        # Octets -> bits
                        # / seconds
                        # / 1,000,000
                        # = Mbps

                        rx_mbps = (
                            rx_diff
                            * 8
                            / elapsed
                            / 1_000_000
                        )


                        tx_mbps = (
                            tx_diff
                            * 8
                            / elapsed
                            / 1_000_000
                        )


                interfaces.append(
                    {
                        "index":
                            current[
                                "index"
                            ],

                        "name":
                            current[
                                "name"
                            ],

                        "admin_status":
                            current[
                                "admin_status"
                            ],

                        "oper_status":
                            current[
                                "oper_status"
                            ],

                        "state":
                            current[
                                "state"
                            ],

                        "rx_mbps":
                            round(
                                rx_mbps,
                                3
                            ),

                        "tx_mbps":
                            round(
                                tx_mbps,
                                3
                            ),

                        "counter_bits":
                            current[
                                "counter_bits"
                            ]
                    }
                )


            interfaces.sort(
                key=lambda item:
                    item["index"]
            )


            # =================================================
            # RAM State
            # =================================================

            monitor_state[
                "switch"
            ] = basic_info


            monitor_state[
                "interfaces"
            ] = interfaces


            monitor_state[
                "events"
            ] = (
                await asyncio.to_thread(
                    get_recent_events,
                    20
                )
            )


            monitor_state[
                "alerts"
            ] = (
                await asyncio.to_thread(
                    get_active_alerts
                )
            )


            monitor_state[
                "last_update"
            ] = current_time


            monitor_state[
                "last_error"
            ] = None


            # =================================================
            # Save Traffic History
            # =================================================

            if (
                previous_time is not None
                and
                (
                    current_time
                    -
                    last_history_save
                )
                >=
                HISTORY_SAVE_SECONDS
            ):

                await asyncio.to_thread(
                    save_interface_history,

                    current_time,

                    interfaces
                )


                last_history_save = (
                    current_time
                )


            # =================================================
            # Save Previous Snapshot
            # =================================================

            previous_interfaces = (
                current_interfaces
            )


            previous_time = (
                current_time
            )


        except Exception as error:

            # 這裡故意把真正錯誤留給我們 debug
            print(
                "POLL ERROR:",
                repr(
                    error
                )
            )


            monitor_state[
                "switch"
            ][
                "online"
            ] = False


            monitor_state[
                "last_error"
            ] = str(
                error
            )


        await asyncio.sleep(
            POLL_SECONDS
        )


# ============================================================
# Database Cleanup Loop
# ============================================================

async def database_cleanup_loop():

    while True:

        try:

            result = (
                await asyncio.to_thread(
                    cleanup_old_data
                )
            )


            print(
                "DATABASE CLEANUP:",
                result
            )


        except Exception as error:

            print(
                "DATABASE CLEANUP ERROR:",
                repr(
                    error
                )
            )


        await asyncio.sleep(
            DATABASE_CLEANUP_SECONDS
        )


# ============================================================
# FastAPI Lifespan
# ============================================================

@asynccontextmanager
async def lifespan(
    app: FastAPI
):

    # 建 DB Tables
    init_db()


    # Background Tasks
    poll_task = (
        asyncio.create_task(
            poll_switch()
        )
    )


    cleanup_task = (
        asyncio.create_task(
            database_cleanup_loop()
        )
    )


    # FastAPI 開始服務
    yield


    # ========================================================
    # Shutdown
    # ========================================================

    poll_task.cancel()

    cleanup_task.cancel()


    try:

        await poll_task

    except asyncio.CancelledError:

        pass


    try:

        await cleanup_task

    except asyncio.CancelledError:

        pass


# ============================================================
# FastAPI App
# ============================================================

app = FastAPI(
    title="Cisco Network Monitor",
    lifespan=lifespan
)


# ============================================================
# Templates
# ============================================================

templates = Jinja2Templates(
    directory=str(
        TEMPLATE_DIR
    )
)


# ============================================================
# Static Files
# ============================================================

app.mount(
    "/static",

    StaticFiles(
        directory=str(
            STATIC_DIR
        )
    ),

    name="static"
)


# ============================================================
# Home
# ============================================================

@app.get("/")
def home(
    request: Request
):

    return templates.TemplateResponse(
        request=request,
        name="index.html"
    )


# ============================================================
# Monitor Page
# ============================================================

@app.get("/monitor")
def monitor(
    request: Request
):

    return templates.TemplateResponse(
        request=request,
        name="monitor.html"
    )


# ============================================================
# Current Monitor API
# ============================================================

@app.get("/api/monitor")
def api_monitor():

    return monitor_state


# ============================================================
# Events API
# ============================================================

@app.get("/api/events")
def api_events():

    return {
        "events":
            get_recent_events(
                50
            )
    }


# ============================================================
# Alerts API
# ============================================================

@app.get("/api/alerts")
def api_alerts():

    return {
        "active":
            get_active_alerts(),

        "recent":
            get_recent_alerts(
                50
            )
    }


# ============================================================
# Alert Rules API
# ============================================================

@app.get("/api/alert-rules")
def api_alert_rules():

    return {
        "rules":
            get_all_alert_rules()
    }


# ============================================================
# Traffic History API
# ============================================================

@app.get(
    "/api/history/{interface_index}"
)
def api_history(
    interface_index: int,
    seconds: int = 3600
):

    # 最多查 7 天
    max_seconds = (
        7
        * 24
        * 60
        * 60
    )


    seconds = max(
        60,

        min(
            seconds,
            max_seconds
        )
    )


    return {
        "interface_index":
            interface_index,

        "seconds":
            seconds,

        "history":
            get_interface_history(
                interface_index,
                seconds
            )
    }


# ============================================================
# Database Status API
# ============================================================

@app.get("/api/database")
def api_database():

    return (
        get_database_status()
    )
