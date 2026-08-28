import time

from collections import (
    defaultdict,
    deque
)

from dataclasses import (
    dataclass,
    asdict
)

from typing import (
    Optional
)


# ============================================================
# Event Type
# ============================================================

EVENT_LINK_DOWN = "LINK_DOWN"
EVENT_LINK_UP = "LINK_UP"


# ============================================================
# Notification Type
# ============================================================

NOTIFY_LINK_DOWN = "LINK_DOWN"
NOTIFY_LINK_UP = "LINK_UP"

NOTIFY_FLAPPING_START = "FLAPPING_START"
NOTIFY_FLAPPING_END = "FLAPPING_END"


# ============================================================
# Notification Decision
#
# Notification Engine 不直接送 Telegram / Email。
#
# 它只負責判斷：
#
#   SEND ?
#   SUPPRESS ?
#
# 之後 Telegram / Email 都只吃這個結果。
# ============================================================

@dataclass
class NotificationDecision:

    action: str

    notification_type: str

    entity_key: str

    reason: str

    timestamp: float

    title: str = ""

    message: str = ""

    event: Optional[dict] = None


    def to_dict(
        self
    ):

        return asdict(
            self
        )


# ============================================================
# Flapping State
# ============================================================

@dataclass
class FlappingState:

    active: bool = False

    started_at: Optional[float] = None

    last_transition_at: Optional[float] = None

    switch_name: str = ""
    switch_ip: str = ""

    interface_index: int = 0
    interface_name: str = ""


# ============================================================
# Suppression State
# ============================================================

@dataclass
class SuppressionState:

    reason: str

    created_at: float

    expires_at: Optional[float] = None


# ============================================================
# Notification Engine
# ============================================================

class NotificationEngine:

    def __init__(
        self,

        # ----------------------------------------------------
        # 同一 notification type 的 cooldown
        #
        # 例如：
        #
        # Gi1/0/1 LINK_DOWN 已通知
        # 5 分鐘內又出現 LINK_DOWN
        #
        # 不再重複通知。
        # ----------------------------------------------------

        cooldown_seconds: int = 300,

        # ----------------------------------------------------
        # Flapping 偵測時間窗
        #
        # 最近 120 秒內計算 transition 次數
        # ----------------------------------------------------

        flap_window_seconds: int = 120,

        # ----------------------------------------------------
        # 幾次 transition 判定為 flapping
        #
        # DOWN
        # UP
        # DOWN
        # UP
        #
        # = 4 次 transition
        # ----------------------------------------------------

        flap_threshold: int = 4,

        # ----------------------------------------------------
        # Flapping 發生後
        #
        # 如果 180 秒完全沒有再 transition
        # 判斷 Port 已經穩定。
        # ----------------------------------------------------

        flap_clear_seconds: int = 180
    ):

        self.cooldown_seconds = (
            cooldown_seconds
        )

        self.flap_window_seconds = (
            flap_window_seconds
        )

        self.flap_threshold = (
            flap_threshold
        )

        self.flap_clear_seconds = (
            flap_clear_seconds
        )


        # ----------------------------------------------------
        # 最後一次真正 SEND 的時間
        #
        # key:
        #
        # 192.168.10.2:1:LINK_DOWN
        # ----------------------------------------------------

        self.last_sent = {}


        # ----------------------------------------------------
        # 每個 interface 最近的 transition
        #
        # {
        #     "192.168.10.2:1": deque([...])
        # }
        # ----------------------------------------------------

        self.transitions = (
            defaultdict(
                deque
            )
        )


        # ----------------------------------------------------
        # 每個 interface 的 Flapping 狀態
        # ----------------------------------------------------

        self.flapping_states = {}


        # ----------------------------------------------------
        # 手動 suppression
        #
        # 未來可拿來做：
        #
        # Maintenance Mode
        # Device Maintenance
        # Port Maintenance
        # ----------------------------------------------------

        self.suppressions = {}


    # ========================================================
    # Entity Key
    # ========================================================

    def make_entity_key(
        self,
        switch_ip,
        interface_index
    ):

        return (
            f"{switch_ip}:"
            f"{interface_index}"
        )


    # ========================================================
    # Notification Cooldown Key
    # ========================================================

    def make_notification_key(
        self,
        entity_key,
        notification_type
    ):

        return (
            f"{entity_key}:"
            f"{notification_type}"
        )


    # ========================================================
    # Cleanup Expired Suppression
    # ========================================================

    def cleanup_suppressions(
        self,
        now=None
    ):

        if now is None:

            now = (
                time.time()
            )


        expired = []


        for (
            entity_key,
            suppression
        ) in self.suppressions.items():

            if (
                suppression.expires_at
                is not None

                and now
                >= suppression.expires_at
            ):

                expired.append(
                    entity_key
                )


        for entity_key in expired:

            del self.suppressions[
                entity_key
            ]


    # ========================================================
    # Manual Suppression
    #
    # duration_seconds = None
    #
    # 代表無限期 suppression
    # ========================================================

    def suppress_interface(
        self,
        switch_ip,
        interface_index,
        reason="maintenance",
        duration_seconds=None
    ):

        now = (
            time.time()
        )


        entity_key = (
            self.make_entity_key(
                switch_ip,
                interface_index
            )
        )


        expires_at = None


        if (
            duration_seconds
            is not None
        ):

            expires_at = (
                now
                + duration_seconds
            )


        self.suppressions[
            entity_key
        ] = SuppressionState(

            reason=reason,

            created_at=now,

            expires_at=expires_at
        )


    # ========================================================
    # Remove Manual Suppression
    # ========================================================

    def unsuppress_interface(
        self,
        switch_ip,
        interface_index
    ):

        entity_key = (
            self.make_entity_key(
                switch_ip,
                interface_index
            )
        )


        self.suppressions.pop(
            entity_key,
            None
        )


    # ========================================================
    # Check Manual Suppression
    # ========================================================

    def get_suppression(
        self,
        entity_key,
        now
    ):

        self.cleanup_suppressions(
            now
        )


        return self.suppressions.get(
            entity_key
        )


    # ========================================================
    # Cooldown Check
    # ========================================================

    def cooldown_allows(
        self,
        entity_key,
        notification_type,
        now
    ):

        notification_key = (
            self.make_notification_key(
                entity_key,
                notification_type
            )
        )


        last_time = (
            self.last_sent.get(
                notification_key
            )
        )


        # ----------------------------------------------------
        # 從來沒有通知過
        #
        # 直接允許
        # ----------------------------------------------------

        if last_time is None:

            return True


        elapsed = (
            now
            - last_time
        )


        return (
            elapsed
            >= self.cooldown_seconds
        )


    # ========================================================
    # Mark Notification Sent
    #
    # 注意：
    #
    # 只有真正決定 SEND 時才呼叫。
    # SUPPRESS 不可以更新 cooldown。
    # ========================================================

    def mark_sent(
        self,
        entity_key,
        notification_type,
        now
    ):

        notification_key = (
            self.make_notification_key(
                entity_key,
                notification_type
            )
        )


        self.last_sent[
            notification_key
        ] = now


    # ========================================================
    # Record Transition
    #
    # LINK_UP / LINK_DOWN 才算 transition。
    # ========================================================

    def record_transition(
        self,
        entity_key,
        timestamp
    ):

        transitions = (
            self.transitions[
                entity_key
            ]
        )


        transitions.append(
            timestamp
        )


        # ----------------------------------------------------
        # 移除 flap window 外的舊資料
        # ----------------------------------------------------

        cutoff = (
            timestamp
            - self.flap_window_seconds
        )


        while (
            transitions

            and transitions[0]
            < cutoff
        ):

            transitions.popleft()


        return len(
            transitions
        )


    # ========================================================
    # Get/Create Flapping State
    # ========================================================

    def get_flapping_state(
        self,
        entity_key
    ):

        if (
            entity_key
            not in self.flapping_states
        ):

            self.flapping_states[
                entity_key
            ] = FlappingState()


        return self.flapping_states[
            entity_key
        ]


    # ========================================================
    # Build LINK Notification
    # ========================================================

    def build_link_notification(
        self,
        event,
        entity_key,
        now
    ):

        event_type = (
            event["event_type"]
        )


        switch_name = (
            event.get(
                "switch_name",
                "Unknown"
            )
        )


        switch_ip = (
            event.get(
                "switch_ip",
                "Unknown"
            )
        )


        interface_name = (
            event.get(
                "interface_name",
                "Unknown"
            )
        )


        if (
            event_type
            == EVENT_LINK_DOWN
        ):

            title = (
                f"Interface DOWN - "
                f"{interface_name}"
            )


            message = (

                f"Switch: {switch_name}\n"
                f"IP: {switch_ip}\n"
                f"Interface: {interface_name}\n"
                f"Status: DOWN"
            )


            notification_type = (
                NOTIFY_LINK_DOWN
            )


        else:

            title = (
                f"Interface UP - "
                f"{interface_name}"
            )


            message = (

                f"Switch: {switch_name}\n"
                f"IP: {switch_ip}\n"
                f"Interface: {interface_name}\n"
                f"Status: UP"
            )


            notification_type = (
                NOTIFY_LINK_UP
            )


        return NotificationDecision(

            action="SEND",

            notification_type=(
                notification_type
            ),

            entity_key=(
                entity_key
            ),

            reason=(
                "normal_link_event"
            ),

            timestamp=now,

            title=title,

            message=message,

            event=event
        )


    # ========================================================
    # Build Flapping Start Notification
    # ========================================================

    def build_flapping_start_notification(
        self,
        event,
        entity_key,
        now,
        transition_count
    ):

        switch_name = (
            event.get(
                "switch_name",
                "Unknown"
            )
        )


        switch_ip = (
            event.get(
                "switch_ip",
                "Unknown"
            )
        )


        interface_name = (
            event.get(
                "interface_name",
                "Unknown"
            )
        )


        title = (
            f"Interface FLAPPING - "
            f"{interface_name}"
        )


        message = (

            f"Switch: {switch_name}\n"
            f"IP: {switch_ip}\n"
            f"Interface: {interface_name}\n"
            f"Status: FLAPPING\n"
            f"Transitions: {transition_count}\n"
            f"Window: {self.flap_window_seconds}s"
        )


        return NotificationDecision(

            action="SEND",

            notification_type=(
                NOTIFY_FLAPPING_START
            ),

            entity_key=(
                entity_key
            ),

            reason=(
                "flapping_detected"
            ),

            timestamp=now,

            title=title,

            message=message,

            event=event
        )


    # ========================================================
    # Build Flapping End Notification
    # ========================================================

    def build_flapping_end_notification(
        self,
        entity_key,
        state,
        now
    ):

        title = (

            f"Interface STABLE - "
            f"{state.interface_name}"
        )


        message = (

            f"Switch: {state.switch_name}\n"
            f"IP: {state.switch_ip}\n"
            f"Interface: {state.interface_name}\n"
            f"Status: STABLE\n"
            f"No transition for "
            f"{self.flap_clear_seconds}s"
        )


        return NotificationDecision(

            action="SEND",

            notification_type=(
                NOTIFY_FLAPPING_END
            ),

            entity_key=(
                entity_key
            ),

            reason=(
                "flapping_cleared"
            ),

            timestamp=now,

            title=title,

            message=message,

            event=None
        )


    # ========================================================
    # Build Suppressed Decision
    # ========================================================

    def build_suppressed(
        self,
        entity_key,
        event,
        now,
        reason
    ):

        return NotificationDecision(

            action="SUPPRESS",

            notification_type=(
                event.get(
                    "event_type",
                    "UNKNOWN"
                )
            ),

            entity_key=(
                entity_key
            ),

            reason=reason,

            timestamp=now,

            event=event
        )


    # ========================================================
    # Process Link Event
    #
    # 這是 Notification Engine 最重要的入口。
    #
    # app.py 未來只需要把 LINK_DOWN / LINK_UP 丟進這裡。
    # ========================================================

    def process_link_event(
        self,
        event
    ):

        now = (
            event.get(
                "timestamp"
            )
        )


        if now is None:

            now = (
                time.time()
            )


        event_type = (
            event.get(
                "event_type"
            )
        )


        # ----------------------------------------------------
        # 只接受 LINK_UP / LINK_DOWN
        # ----------------------------------------------------

        if event_type not in (
            EVENT_LINK_DOWN,
            EVENT_LINK_UP
        ):

            raise ValueError(

                "NotificationEngine only accepts "
                "LINK_DOWN or LINK_UP"
            )


        switch_ip = (
            event.get(
                "switch_ip",
                "unknown"
            )
        )


        interface_index = (
            event.get(
                "interface_index"
            )
        )


        if interface_index is None:

            raise ValueError(

                "event requires "
                "'interface_index'"
            )


        entity_key = (
            self.make_entity_key(
                switch_ip,
                interface_index
            )
        )


        # ====================================================
        # Suppression #1
        #
        # Manual Maintenance Suppression
        # ====================================================

        manual_suppression = (
            self.get_suppression(
                entity_key,
                now
            )
        )


        if manual_suppression:

            return self.build_suppressed(

                entity_key=entity_key,

                event=event,

                now=now,

                reason=(
                    "manual_suppression:"
                    f"{manual_suppression.reason}"
                )
            )


        # ====================================================
        # Suppression #2
        #
        # admin down
        #
        # 管理員 shutdown port
        # 不應該當作故障轟通知。
        # ====================================================

        admin_status = str(

            event.get(
                "admin_status",
                ""
            )

        ).lower()


        if (
            event_type
            == EVENT_LINK_DOWN

            and admin_status
            in (
                "down",
                "2"
            )
        ):

            return self.build_suppressed(

                entity_key=entity_key,

                event=event,

                now=now,

                reason="admin_down"
            )


        # ====================================================
        # Record Transition
        # ====================================================

        transition_count = (
            self.record_transition(
                entity_key,
                now
            )
        )


        flap_state = (
            self.get_flapping_state(
                entity_key
            )
        )


        # 每次 transition 都更新
        flap_state.last_transition_at = now

        flap_state.switch_name = (
            event.get(
                "switch_name",
                "Unknown"
            )
        )

        flap_state.switch_ip = (
            event.get(
                "switch_ip",
                "Unknown"
            )
        )

        flap_state.interface_index = (
            interface_index
        )

        flap_state.interface_name = (
            event.get(
                "interface_name",
                "Unknown"
            )
        )


        # ====================================================
        # Flapping Detection
        # ====================================================

        if (
            not flap_state.active

            and transition_count
            >= self.flap_threshold
        ):

            flap_state.active = True

            flap_state.started_at = now


            # ------------------------------------------------
            # Flapping Start 只送一次。
            #
            # 此時不要再送普通 LINK_UP / LINK_DOWN。
            # ------------------------------------------------

            notification_type = (
                NOTIFY_FLAPPING_START
            )


            if self.cooldown_allows(

                entity_key,
                notification_type,
                now
            ):

                self.mark_sent(

                    entity_key,
                    notification_type,
                    now
                )


                return (
                    self
                    .build_flapping_start_notification(

                        event=event,

                        entity_key=entity_key,

                        now=now,

                        transition_count=(
                            transition_count
                        )
                    )
                )


            return self.build_suppressed(

                entity_key=entity_key,

                event=event,

                now=now,

                reason=(
                    "flapping_start_cooldown"
                )
            )


        # ====================================================
        # Suppression #3
        #
        # 已經在 flapping 狀態
        #
        # 普通 LINK_DOWN / LINK_UP 全部壓掉。
        # ====================================================

        if flap_state.active:

            return self.build_suppressed(

                entity_key=entity_key,

                event=event,

                now=now,

                reason="interface_flapping"
            )


        # ====================================================
        # Normal Notification
        # ====================================================

        if (
            event_type
            == EVENT_LINK_DOWN
        ):

            notification_type = (
                NOTIFY_LINK_DOWN
            )

        else:

            notification_type = (
                NOTIFY_LINK_UP
            )


        # ====================================================
        # Cooldown
        # ====================================================

        if not self.cooldown_allows(

            entity_key,
            notification_type,
            now
        ):

            return self.build_suppressed(

                entity_key=entity_key,

                event=event,

                now=now,

                reason="cooldown"
            )


        # ----------------------------------------------------
        # 確定 SEND
        #
        # 現在才寫入 last_sent。
        # ----------------------------------------------------

        self.mark_sent(

            entity_key,
            notification_type,
            now
        )


        return self.build_link_notification(

            event=event,

            entity_key=entity_key,

            now=now
        )


    # ========================================================
    # Tick
    #
    # 每一輪 SNMP Poll 都可以呼叫。
    #
    # 即使現在沒有 LINK event，
    # Engine 也可以判斷：
    #
    # 「這個 flapping port 已經穩定 180 秒」
    #
    # 然後產生 FLAPPING_END。
    # ========================================================

    def tick(
        self,
        now=None
    ):

        if now is None:

            now = (
                time.time()
            )


        decisions = []


        self.cleanup_suppressions(
            now
        )


        for (
            entity_key,
            state
        ) in self.flapping_states.items():

            if not state.active:

                continue


            if (
                state.last_transition_at
                is None
            ):

                continue


            stable_seconds = (

                now
                - state.last_transition_at
            )


            if (
                stable_seconds
                < self.flap_clear_seconds
            ):

                continue


            # ------------------------------------------------
            # 已穩定
            # ------------------------------------------------

            state.active = False


            notification_type = (
                NOTIFY_FLAPPING_END
            )


            if self.cooldown_allows(

                entity_key,
                notification_type,
                now
            ):

                self.mark_sent(

                    entity_key,
                    notification_type,
                    now
                )


                decisions.append(

                    self
                    .build_flapping_end_notification(

                        entity_key=entity_key,

                        state=state,

                        now=now
                    )
                )


            # ------------------------------------------------
            # 清掉舊 transition
            #
            # 下一次重新計算。
            # ------------------------------------------------

            self.transitions[
                entity_key
            ].clear()


        return decisions


    # ========================================================
    # Debug Status
    #
    # 之後可以直接做：
    #
    # GET /api/notification-engine
    # ========================================================

    def get_status(
        self
    ):

        flapping = {}


        for (
            entity_key,
            state
        ) in self.flapping_states.items():

            flapping[
                entity_key
            ] = asdict(
                state
            )


        suppressions = {}


        for (
            entity_key,
            state
        ) in self.suppressions.items():

            suppressions[
                entity_key
            ] = asdict(
                state
            )


        transitions = {}


        for (
            entity_key,
            values
        ) in self.transitions.items():

            transitions[
                entity_key
            ] = list(
                values
            )


        return {

            "config": {

                "cooldown_seconds":
                    self.cooldown_seconds,

                "flap_window_seconds":
                    self.flap_window_seconds,

                "flap_threshold":
                    self.flap_threshold,

                "flap_clear_seconds":
                    self.flap_clear_seconds
            },


            "last_sent":
                dict(
                    self.last_sent
                ),


            "transitions":
                transitions,


            "flapping":
                flapping,


            "suppressions":
                suppressions
        }
