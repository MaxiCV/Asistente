class ChatError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def history_unavailable():
    return ChatError(
        503,
        "chat_history_unavailable",
        "No se pudo confirmar el historial. Reintenta el mismo envío.",
    )
