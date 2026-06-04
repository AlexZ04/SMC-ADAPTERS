ADMIN_QUEUE_NAME = "smc_tg_admin_panel"
TG_ADMIN_QUEUE_NAME = "smc_tg_admin_panel"
VK_ADMIN_QUEUE_NAME = "smc_vk_admin_panel"
TG_USER_QUEUE_NAME = "smc_tg_user"
VK_USER_QUEUE_NAME = "smc_vk_user"
DEFAULT_ADMIN_ENDPOINT = "/api/v1/admin"
REPLY_KEYBOARD_HELP_TEXT = (
    "Сделать выбор можно либо нажав на одну из кнопок выше, либо введите текст вручную.\n"
    "Для возвращения в главное меню нажмите \"К боту\""
)

TELEGRAM_FIELD_REPLY_MARKUP = "reply_markup"
TELEGRAM_FIELD_INLINE_KEYBOARD = "inline_keyboard"
TELEGRAM_FIELD_KEYBOARD = "keyboard"
TELEGRAM_FIELD_RESIZE_KEYBOARD = "resize_keyboard"
TELEGRAM_FIELD_ONE_TIME_KEYBOARD = "one_time_keyboard"
TELEGRAM_FIELD_CALLBACK_DATA = "callback_data"
TELEGRAM_FIELD_TEXT = "text"
TELEGRAM_FIELD_URL = "url"
TELEGRAM_FIELD_STYLE = "style"

TELEGRAM_BUTTON_STYLE_DANGER = "danger"
TELEGRAM_BUTTON_STYLE_SUCCESS = "success"
TELEGRAM_BUTTON_STYLE_PRIMARY = "primary"
VK_BUTTON_STYLE_PRIMARY = "primary"
VK_BUTTON_STYLE_SECONDARY = "secondary"
VK_BUTTON_STYLE_POSITIVE = "positive"

TELEGRAM_BUTTON_COLOR_TO_STYLE = {
    TELEGRAM_BUTTON_STYLE_DANGER: TELEGRAM_BUTTON_STYLE_DANGER,
    "red": TELEGRAM_BUTTON_STYLE_DANGER,
    "красный": TELEGRAM_BUTTON_STYLE_DANGER,
    "#f44336": TELEGRAM_BUTTON_STYLE_DANGER,
    "#ff0000": TELEGRAM_BUTTON_STYLE_DANGER,
    TELEGRAM_BUTTON_STYLE_SUCCESS: TELEGRAM_BUTTON_STYLE_SUCCESS,
    "green": TELEGRAM_BUTTON_STYLE_SUCCESS,
    "зеленый": TELEGRAM_BUTTON_STYLE_SUCCESS,
    "зелёный": TELEGRAM_BUTTON_STYLE_SUCCESS,
    "#4caf50": TELEGRAM_BUTTON_STYLE_SUCCESS,
    "#00ff00": TELEGRAM_BUTTON_STYLE_SUCCESS,
    TELEGRAM_BUTTON_STYLE_PRIMARY: TELEGRAM_BUTTON_STYLE_PRIMARY,
    "blue": TELEGRAM_BUTTON_STYLE_PRIMARY,
    "синий": TELEGRAM_BUTTON_STYLE_PRIMARY,
    "#2196f3": TELEGRAM_BUTTON_STYLE_PRIMARY,
    "#0000ff": TELEGRAM_BUTTON_STYLE_PRIMARY,
}

VK_BUTTON_COLOR_TO_STYLE = {
    "white": VK_BUTTON_STYLE_SECONDARY,
    "black": VK_BUTTON_STYLE_PRIMARY,
    "green": VK_BUTTON_STYLE_POSITIVE,
}

ADMIN_ROLES = {"ADMIN", "SUPER_ADMIN"}
USER_ROLE = "USER"
ADMIN_CHANNEL = "admin-channel"
USER_CHANNEL = "user-channel"

QUEUE_BY_PLATFORM_AND_ROLE = {
    ("TG", "ADMIN"): TG_ADMIN_QUEUE_NAME,
    ("TG", "SUPER_ADMIN"): TG_ADMIN_QUEUE_NAME,
    ("VK", "ADMIN"): VK_ADMIN_QUEUE_NAME,
    ("VK", "SUPER_ADMIN"): VK_ADMIN_QUEUE_NAME,
    ("TG", "USER"): TG_USER_QUEUE_NAME,
    ("VK", "USER"): VK_USER_QUEUE_NAME,
}

QUEUE_BY_PLATFORM_AND_CHANNEL = {
    ("TG", ADMIN_CHANNEL): TG_ADMIN_QUEUE_NAME,
    ("VK", ADMIN_CHANNEL): VK_ADMIN_QUEUE_NAME,
    ("TG", USER_CHANNEL): TG_USER_QUEUE_NAME,
    ("VK", USER_CHANNEL): VK_USER_QUEUE_NAME,
}


def makeQueueName(base_queue_name: str, queue_prefix: str) -> str:
    return f"{queue_prefix}_{base_queue_name}"


def buildQueueByPlatformAndRole(queue_prefix: str) -> dict[tuple[str, str], str]:
    return {
        key: makeQueueName(baseQueueName, queue_prefix)
        for key, baseQueueName in QUEUE_BY_PLATFORM_AND_ROLE.items()
    }


def buildQueueByPlatformAndChannel(queue_prefix: str) -> dict[tuple[str, str], str]:
    return {
        key: makeQueueName(baseQueueName, queue_prefix)
        for key, baseQueueName in QUEUE_BY_PLATFORM_AND_CHANNEL.items()
    }

ADAPTER_BY_PLATFORM_AND_ROLE = {
    ("TG", "ADMIN"): "telegram_admin",
    ("TG", "SUPER_ADMIN"): "telegram_admin",
    ("VK", "ADMIN"): "vk_admin",
    ("VK", "SUPER_ADMIN"): "vk_admin",
    ("TG", "USER"): "telegram_user",
    ("VK", "USER"): "vk_user",
}

ADAPTER_BY_PLATFORM_AND_CHANNEL = {
    ("TG", ADMIN_CHANNEL): "telegram_admin",
    ("VK", ADMIN_CHANNEL): "vk_admin",
    ("TG", USER_CHANNEL): "telegram_user",
    ("VK", USER_CHANNEL): "vk_user",
}
