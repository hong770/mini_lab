import subprocess


# ============================================================
# Switch 基本設定
# ============================================================

SWITCH_IP = "192.168.10.2"
COMMUNITY = "monitor"


# ============================================================
# Switch 基本資訊 OID
# ============================================================

SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"

# Cisco CPU 1 minute
CPU_1MIN = "1.3.6.1.4.1.9.2.1.56.0"


# ============================================================
# Interface OID
# ============================================================

# Interface 名稱
IF_DESCR = "1.3.6.1.2.1.2.2.1.2"

# Admin Status
# 1 = UP
# 2 = DOWN
# 3 = TESTING
IF_ADMIN_STATUS = "1.3.6.1.2.1.2.2.1.7"

# Operational Status
IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"


# ============================================================
# Traffic Counter
# ============================================================

# 舊版 32-bit Counter
IF_IN_OCTETS = "1.3.6.1.2.1.2.2.1.10"
IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16"

# 64-bit High Capacity Counter
# Gigabit Ethernet 建議優先使用這兩個
IF_HC_IN_OCTETS = "1.3.6.1.2.1.31.1.1.1.6"
IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10"


# ============================================================
# SNMP GET
# ============================================================

def snmp_get(oid):

    try:

        result = subprocess.run(
            [
                "snmpget",
                "-v2c",
                "-c", COMMUNITY,
                "-Oqv",
                SWITCH_IP,
                oid
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return None

        return result.stdout.strip()

    except subprocess.TimeoutExpired:

        return None

    except Exception as error:

        print(
            "SNMP GET error:",
            error
        )

        return None


# ============================================================
# SNMP WALK
# ============================================================

def snmp_walk(oid):

    try:

        result = subprocess.run(
            [
                "snmpwalk",
                "-v2c",
                "-c", COMMUNITY,

                # Numeric OID
                # 方便 Python 取得最後的 ifIndex
                "-On",

                SWITCH_IP,
                oid
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            return []

        return result.stdout.splitlines()

    except subprocess.TimeoutExpired:

        return []

    except Exception as error:

        print(
            "SNMP WALK error:",
            error
        )

        return []


# ============================================================
# 解析 SNMP WALK
# ============================================================

def parse_walk(lines):

    data = {}

    for line in lines:

        if " = " not in line:
            continue

        oid, value = line.split(
            " = ",
            1
        )

        # OID 最後一段就是 ifIndex
        index = oid.split(".")[-1]

        data[index] = value

    return data


# ============================================================
# 解析 Interface Status
# ============================================================

def parse_status(value):

    value = (
        value
        .replace("INTEGER: ", "")
        .strip()
    )

    status_map = {
        "1": "UP",
        "2": "DOWN",
        "3": "TESTING",
        "4": "UNKNOWN",
        "5": "DORMANT",
        "6": "NOT PRESENT",
        "7": "LOWER LAYER DOWN"
    }

    return status_map.get(
        value,
        "UNKNOWN"
    )


# ============================================================
# 解析 Counter
# ============================================================

def parse_counter(value):

    value = (
        value
        .replace("Counter32: ", "")
        .replace("Counter64: ", "")
        .strip()
    )

    try:

        return int(value)

    except (ValueError, TypeError):

        return 0


# ============================================================
# 清理 STRING
# ============================================================

def clean_string(value):

    if value is None:
        return None

    return (
        value
        .replace("STRING: ", "")
        .replace('"', "")
        .strip()
    )


# ============================================================
# Switch 基本資訊
# ============================================================

def get_basic_info():

    hostname = snmp_get(
        SYS_NAME
    )

    uptime = snmp_get(
        SYS_UPTIME
    )

    cpu = snmp_get(
        CPU_1MIN
    )

    return {
        "ip": SWITCH_IP,

        "hostname":
            clean_string(hostname),

        "uptime":
            uptime,

        "cpu":
            cpu,

        "online":
            hostname is not None
    }


# ============================================================
# Interface Snapshot
# ============================================================

def get_interface_snapshot():

    descriptions = parse_walk(
        snmp_walk(
            IF_DESCR
        )
    )

    admin_statuses = parse_walk(
        snmp_walk(
            IF_ADMIN_STATUS
        )
    )

    oper_statuses = parse_walk(
        snmp_walk(
            IF_OPER_STATUS
        )
    )


    # --------------------------------------------------------
    # 優先讀 64-bit Counter
    # --------------------------------------------------------

    hc_rx = parse_walk(
        snmp_walk(
            IF_HC_IN_OCTETS
        )
    )

    hc_tx = parse_walk(
        snmp_walk(
            IF_HC_OUT_OCTETS
        )
    )


    # --------------------------------------------------------
    # 如果設備不支援 64-bit，再使用 32-bit
    # --------------------------------------------------------

    use_high_capacity = (
        len(hc_rx) > 0
        and len(hc_tx) > 0
    )


    if use_high_capacity:

        rx_data = hc_rx
        tx_data = hc_tx

        counter_bits = 64

    else:

        rx_data = parse_walk(
            snmp_walk(
                IF_IN_OCTETS
            )
        )

        tx_data = parse_walk(
            snmp_walk(
                IF_OUT_OCTETS
            )
        )

        counter_bits = 32


    interfaces = {}


    for index, description in descriptions.items():

        name = (
            description
            .replace("STRING: ", "")
            .replace('"', "")
            .strip()
        )


        admin_status = parse_status(
            admin_statuses.get(
                index,
                ""
            )
        )


        oper_status = parse_status(
            oper_statuses.get(
                index,
                ""
            )
        )


        # ----------------------------------------------------
        # 判斷 Port 狀態
        # ----------------------------------------------------

        if admin_status == "DOWN":

            state = "SHUTDOWN"

        elif oper_status == "UP":

            state = "ONLINE"

        else:

            state = "NO LINK"


        interfaces[index] = {
            "index":
                int(index),

            "name":
                name,

            "admin_status":
                admin_status,

            "oper_status":
                oper_status,

            "state":
                state,

            "rx_counter":
                parse_counter(
                    rx_data.get(
                        index,
                        ""
                    )
                ),

            "tx_counter":
                parse_counter(
                    tx_data.get(
                        index,
                        ""
                    )
                ),

            "counter_bits":
                counter_bits
        }


    return interfaces
