import imaplib
from typing import Union

FetchResponse = Union[list[None], list[Union[bytes, tuple[bytes, bytes]]]]

old_fetch = imaplib.IMAP4_SSL.fetch


def imap_fetch(self: imaplib.IMAP4, message_set: str, message_parts: str) -> tuple[str, FetchResponse]:
    response, data = old_fetch(self, message_set, message_parts)
    return response, data


imaplib.IMAP4_SSL.fetch = imap_fetch  # type: ignore
