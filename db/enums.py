# @Important: Don't make it an enum (type from `typing` module) - keep it `str` type for the sake of db


class AccountType:
    COMMON = 1
    MEDIC = 2
    SOCIAL = 3


class PermissionLevel:
    DEFAULT = 0
    BROADCASTER = 1
    ADMIN = 2
    MAX = ADMIN


class ServiceTypes:
    TELEGRAM = "telegram"
    FACEBOOK = "facebook"
    WEBSITE = "website"
