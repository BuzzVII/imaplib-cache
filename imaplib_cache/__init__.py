import imaplib
import os
import logging
from typing import Union, Optional, Literal, Callable

from sqlmodel import Field, SQLModel, UniqueConstraint, create_engine, Session, select

logger = logging.getLogger()
logging.basicConfig(level=logging.INFO)

FetchResponse = Union[list[None], list[Union[bytes, tuple[bytes, bytes]]]]

old_login: Union[None, Callable] = None
old_fetch: Union[None, Callable] = None


class Fetch(SQLModel, table=True):  # type: ignore
    __table_args__ = (UniqueConstraint("hash"),)
    id_: Optional[int] = Field(default=None, primary_key=True)
    hash: str = Field(index=True, max_length=128)
    user: str = Field(max_length=128)
    data: bytes = Field(max_length=1024**2 * 10)  # 10MB maximum


SQLALCHEMY_DATABASE_URL = os.environ.get("SQLALCHEMY_DATABASE_URI", "sqlite:///imaplib_cache.sqlite")
db_engine = create_engine(SQLALCHEMY_DATABASE_URL)
SQLModel.metadata.create_all(db_engine)


def parse_uid(response: bytes) -> tuple[str, str]:
    message_id, tag, uid = response.split()
    return message_id.decode(), uid[:-1].decode()  # remove trailing parenthesis


def cache_entry(user: str, uids: dict[str, str], message_id: str, message_parts: str, data: bytes) -> Fetch:
    uid = uids[message_id]
    hash_ = f"{uid} {message_parts}"
    return Fetch(hash=hash_, user=user, data=data)


def imap_login(self: imaplib.IMAP4, user: str, password: str) -> tuple[Literal["OK"], list[bytes]]:
    self.user = user  # type: ignore
    if old_login is None:
        raise RuntimeError("Original patched function have not been saved properly")
    return old_login(self, user, password)


def imap_fetch(
    self: imaplib.IMAP4, message_set: Union[Union[str, bytes]], message_parts: str
) -> tuple[bytes, FetchResponse]:
    """Function for monkey patching the imaplib fetch function

    response = [OK, BAD, NO]
    data = [(b'{message_id} ({message_set} {#}', b'{DATA}'), b')', ...]
    """
    global old_login, old_fetch
    if isinstance(message_set, bytes):
        message_set = message_set.decode()
    if old_fetch is None:
        raise RuntimeError("Original patched function have not been saved properly")
    _, uid_data = old_fetch(self, message_set, "(UID)")
    uid_list = [parse_uid(d) for d in uid_data]
    uids = {key: value for key, value in uid_list}
    message_ids = message_set.split(",")
    new_message_set = []
    cached_data = []
    with Session(db_engine) as session:
        for message_id in message_ids:
            uid = uids[message_id]
            hash_ = f"{uid} {message_parts}"
            cache_hit = session.exec(select(Fetch).where(Fetch.hash == hash_ and Fetch.user == self.user)).one_or_none()
            if cache_hit:
                logger.info(f"cache hit for {message_id}")
                cached_data.append((f"{message_id} ({message_parts}".encode(), cache_hit.data))
            else:
                new_message_set.append(message_id)
        if len(new_message_set) > 0:
            response, data = old_fetch(self, ",".join(new_message_set), message_parts)
        else:
            data = []
        for datum in data:
            if isinstance(datum, tuple):
                message_id = datum[0].split()[0].decode()
                datum = datum[1]
                if len(datum) > 1024**2 * 10:
                    logger.warning("Data size too large for cache")
                    continue
                session.add(cache_entry(self.user, uids, message_id, message_parts, datum))
        session.commit()
    for datum in cached_data:
        data.append(datum)
        data.append(b")")
    return response, data


def install_cache():
    global old_login, old_fetch
    old_login = imaplib.IMAP4_SSL.login
    # patch the login function to store the user for cache lookup
    imaplib.IMAP4_SSL.login = imap_login  # type: ignore

    old_fetch = imaplib.IMAP4_SSL.fetch
    # patch the fetch function with the cache check function
    imaplib.IMAP4_SSL.fetch = imap_fetch  # type: ignore


def remove_cache():
    global old_login, old_fetch

    imaplib.IMAP4_SSL.login = old_login  # type: ignore
    imaplib.IMAP4_SSL.fetch = old_fetch  # type: ignore


# TODO: Implement IMAP_CACHED class instead of monkey patching the methods
# TODO: Patch the uid('fetch', ...) method
# TODO: Move the database to something along the lines of RFC822
