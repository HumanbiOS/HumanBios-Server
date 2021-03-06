import hashlib


class UserIdentity:
    @staticmethod
    def hash(user_id, service_in):
        return hashlib.sha1(f"{user_id}{service_in}".encode()).hexdigest()
