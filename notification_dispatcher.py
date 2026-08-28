import os
import smtplib
import ssl

from email.message import EmailMessage


# ============================================================
# SMTP Configuration
#
# 不要把密碼寫死在 Python。
#
# 從 Linux environment variable 讀取。
#
# 需要：
#
# SMTP_HOST
# SMTP_PORT
# SMTP_USERNAME
# SMTP_PASSWORD
# SMTP_FROM
# SMTP_TO
#
# 例如 Gmail：
#
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# ============================================================


def get_email_config():

    # --------------------------------------------------------
    # SMTP Server
    # --------------------------------------------------------

    smtp_host = os.getenv(
        "SMTP_HOST",
        ""
    ).strip()


    # --------------------------------------------------------
    # SMTP Port
    #
    # 587 = STARTTLS
    # --------------------------------------------------------

    smtp_port = int(
        os.getenv(
            "SMTP_PORT",
            "587"
        )
    )


    # --------------------------------------------------------
    # SMTP Login Account
    # --------------------------------------------------------

    smtp_username = os.getenv(
        "SMTP_USERNAME",
        ""
    ).strip()


    # --------------------------------------------------------
    # SMTP Password
    #
    # Gmail 建議使用 App Password。
    # 不要使用一般 Gmail 登入密碼。
    # --------------------------------------------------------

    smtp_password = os.getenv(
        "SMTP_PASSWORD",
        ""
    )


    # --------------------------------------------------------
    # From
    # --------------------------------------------------------

    smtp_from = os.getenv(
        "SMTP_FROM",
        smtp_username
    ).strip()


    # --------------------------------------------------------
    # To
    #
    # 可以支援：
    #
    # user1@example.com,user2@example.com
    # --------------------------------------------------------

    smtp_to_raw = os.getenv(
        "SMTP_TO",
        ""
    )


    smtp_to = [

        item.strip()

        for item in smtp_to_raw.split(",")

        if item.strip()
    ]


    return {

        "host":
            smtp_host,

        "port":
            smtp_port,

        "username":
            smtp_username,

        "password":
            smtp_password,

        "from":
            smtp_from,

        "to":
            smtp_to
    }


# ============================================================
# Validate Configuration
# ============================================================

def validate_email_config(
    config
):

    missing = []


    if not config["host"]:

        missing.append(
            "SMTP_HOST"
        )


    if not config["username"]:

        missing.append(
            "SMTP_USERNAME"
        )


    if not config["password"]:

        missing.append(
            "SMTP_PASSWORD"
        )


    if not config["from"]:

        missing.append(
            "SMTP_FROM"
        )


    if not config["to"]:

        missing.append(
            "SMTP_TO"
        )


    if missing:

        raise RuntimeError(

            "Missing SMTP environment variables: "
            + ", ".join(
                missing
            )
        )


# ============================================================
# Build Email Subject
# ============================================================

def build_subject(
    decision
):

    # --------------------------------------------------------
    # decision.title
    #
    # Notification Engine 已經建立，例如：
    #
    # Interface DOWN - Gi1/0/1
    #
    # Interface FLAPPING - Gi1/0/1
    #
    # Interface STABLE - Gi1/0/1
    # --------------------------------------------------------

    title = (
        decision.title
        or decision.notification_type
    )


    return (
        f"[Mini-Lab Alert] {title}"
    )


# ============================================================
# Build Email Body
# ============================================================

def build_body(
    decision
):

    lines = []


    # ========================================================
    # Main Notification Message
    # ========================================================

    if decision.message:

        lines.append(
            decision.message
        )


    # ========================================================
    # Additional Debug / Diagnostic Information
    #
    # 對 Lab 很有用。
    #
    # 你收到信可以直接知道：
    #
    # notification type
    # entity
    # reason
    # timestamp
    # ========================================================

    lines.append(
        ""
    )

    lines.append(
        "----------------------------------------"
    )

    lines.append(
        "Mini-Lab Notification Engine"
    )

    lines.append(
        "----------------------------------------"
    )


    lines.append(

        "Notification Type: "
        f"{decision.notification_type}"
    )


    lines.append(

        "Entity: "
        f"{decision.entity_key}"
    )


    lines.append(

        "Reason: "
        f"{decision.reason}"
    )


    lines.append(

        "Timestamp: "
        f"{decision.timestamp}"
    )


    return "\n".join(
        lines
    )


# ============================================================
# Send Email
# ============================================================

def send_email(
    decision
):

    # ========================================================
    # Safety
    #
    # Dispatcher 理論上只會收到 SEND。
    #
    # 但這裡再防守一次。
    #
    # SUPPRESS 永遠不能寄 Email。
    # ========================================================

    if decision.action != "SEND":

        return {

            "success":
                False,

            "skipped":
                True,

            "reason":
                "decision_not_send"
        }


    # ========================================================
    # Configuration
    # ========================================================

    config = (
        get_email_config()
    )


    validate_email_config(
        config
    )


    # ========================================================
    # Build Message
    # ========================================================

    message = EmailMessage()


    message[
        "Subject"
    ] = build_subject(
        decision
    )


    message[
        "From"
    ] = config[
        "from"
    ]


    message[
        "To"
    ] = ", ".join(
        config[
            "to"
        ]
    )


    message.set_content(

        build_body(
            decision
        )
    )


    # ========================================================
    # TLS Context
    #
    # 使用 Python 系統預設 CA 驗證 SMTP Server。
    # ========================================================

    context = (
        ssl.create_default_context()
    )


    # ========================================================
    # SMTP Connection
    #
    # Port 587:
    #
    # Connect
    #     ↓
    # EHLO
    #     ↓
    # STARTTLS
    #     ↓
    # EHLO
    #     ↓
    # LOGIN
    #     ↓
    # SEND
    # ========================================================

    with smtplib.SMTP(

        config["host"],

        config["port"],

        timeout=15

    ) as server:


        # ----------------------------------------------------
        # SMTP Greeting
        # ----------------------------------------------------

        server.ehlo()


        # ----------------------------------------------------
        # Upgrade plain SMTP connection → TLS
        # ----------------------------------------------------

        server.starttls(
            context=context
        )


        # ----------------------------------------------------
        # TLS 建立後重新 EHLO
        # ----------------------------------------------------

        server.ehlo()


        # ----------------------------------------------------
        # Authentication
        # ----------------------------------------------------

        server.login(

            config[
                "username"
            ],

            config[
                "password"
            ]
        )


        # ----------------------------------------------------
        # Send
        # ----------------------------------------------------

        server.send_message(
            message
        )


    return {

        "success":
            True,

        "skipped":
            False,

        "notification_type":
            decision.notification_type,

        "entity_key":
            decision.entity_key,

        "recipients":
            config["to"]
    }


# ============================================================
# Dispatcher
#
# 未來如果要多一種通知：
#
# Email
# Discord
# Slack
# Webhook
#
# 就從這裡擴充。
#
# Notification Engine 完全不用修改。
# ============================================================

def dispatch(
    decision
):

    # --------------------------------------------------------
    # SUPPRESS
    #
    # 不進任何 notification channel。
    # --------------------------------------------------------

    if decision.action != "SEND":

        return {

            "success":
                False,

            "skipped":
                True,

            "reason":
                "suppressed"
        }


    # --------------------------------------------------------
    # 現階段只有 Email
    # --------------------------------------------------------

    return send_email(
        decision
    )
