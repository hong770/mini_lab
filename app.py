import asyncio
import time

from contextlib import asynccontextmanager

from fastapi import FastAPI

from fastapi import Request

from fastapi.templating import (
    Jinja2Templates
)

from fastapi.staticfiles import (
    StaticFiles
)


from snmp import (
    get_basic_info,
    get_interface_snapshot
)


from database import (
    init_db,
    save_interface_history,
    get_interface_history,
    cleanup_old_history,
    get_database_status
)


# ============================================================
# Poll 設定
# ============================================================

# SNMP 即時監控每 5 秒
POLL_SECONDS = 5

# 歷史資料每 30 秒存一次
# 不需要每 5 秒全部塞 SQLite
HISTORY_SAVE_SECONDS = 30

# Database Cleanup 每 1 小時執行一次
DATABASE_CLEANUP_SECONDS = 3600


# ============================================================
# RAM Current State
# ============================================================

monitor_state = {

    "switch": {
        "online":
            False,

        "hostname":
            "Unknown",

        "ip":
            "192.168.10.2",

        "uptime":
            None,

        "cpu":
            None
    },


    "interfaces": [],


    "last_update":
        None
}


# ============================================================
# Counter 差值
# ============================================================

def calculate_counter_diff(
    current,
    previous,
    counter_bits
):

    diff = (
        current
        - previous
    )


    # --------------------------------------------------------
    # Counter rollover
    # --------------------------------------------------------

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
# Background SNMP Poller
# ============================================================

async def poll_switch():

    previous_interfaces = {}

    previous_time = None

    last_history_save = 0


    while True:

        try:

            # ------------------------------------------------
            # SNMP 是 blocking command
            #
            # 放到 thread
            # 避免卡住 FastAPI
            # ------------------------------------------------

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


            interfaces = []


            # ------------------------------------------------
            # 計算每個 Port Mbps
            # ------------------------------------------------

            for index, current in current_interfaces.items():

                rx_mbps = 0.0

                tx_mbps = 0.0


                if (
                    previous_time
                    is not None

                    and index
                    in previous_interfaces
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
                            current["index"],

                        "name":
                            current["name"],

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


            # ------------------------------------------------
            # 更新 RAM Current State
            # ------------------------------------------------

            monitor_state[
                "switch"
            ] = basic_info


            monitor_state[
                "interfaces"
            ] = interfaces


            monitor_state[
                "last_update"
            ] = current_time


            # ------------------------------------------------
            # 歷史資料每 30 秒存一次
            # ------------------------------------------------

            if (
                previous_time
                is not None

                and (
                    current_time
                    -
                    last_history_save
                )
                >= HISTORY_SAVE_SECONDS
            ):

                await asyncio.to_thread(
                    save_interface_history,

                    current_time,

                    interfaces
                )


                last_history_save = (
                    current_time
                )


            # ------------------------------------------------
            # 保留這次 Counter
            #
            # 下一輪拿來算差值
            # ------------------------------------------------

            previous_interfaces = (
                current_interfaces
            )


            previous_time = (
                current_time
            )


        except Exception as error:

            print(
                "Poll error:",
                error
            )


            monitor_state[
                "switch"
            ][
                "online"
            ] = False


        await asyncio.sleep(
            POLL_SECONDS
        )


# ============================================================
# Database Cleanup Background Task
# ============================================================

async def database_cleanup_loop():

    while True:

        try:

            await asyncio.to_thread(
                cleanup_old_history
            )

        except Exception as error:

            print(
                "Database cleanup error:",
                error
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

    # 建立 SQLite
    init_db()


    # 啟動 SNMP Poller
    poll_task = (
        asyncio.create_task(
            poll_switch()
        )
    )


    # 啟動 Database Cleanup
    cleanup_task = (
        asyncio.create_task(
            database_cleanup_loop()
        )
    )


    yield


    # --------------------------------------------------------
    # 關閉 FastAPI 時停止 Background Tasks
    # --------------------------------------------------------

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
# FastAPI
# ============================================================

app = FastAPI(
    title="Cisco 3750G Monitor",
    lifespan=lifespan
)


templates = Jinja2Templates(
    directory="templates"
)


app.mount(
    "/static",

    StaticFiles(
        directory="static"
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
# Interface History API
# ============================================================

@app.get(
    "/api/history/{interface_index}"
)
def api_history(
    interface_index: int,
    seconds: int = 3600
):

    # --------------------------------------------------------
    # 防止一次要求太大的資料
    #
    # 最多只允許看 7 天
    # --------------------------------------------------------

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

    return get_database_status()
