from abc import ABC
import datetime
import logging
import sqlite3
from typing import Optional
from kinobot.exceptions import KinoException

import pydantic

logger = logging.getLogger(__name__)

MIN_BYTES = None


class MissingPermission(KinoException):
    pass


class TicketLog(pydantic.BaseModel):
    ticket_id: int
    request_id: str
    added: datetime.datetime


class Ticket(pydantic.BaseModel):
    id: int
    user_id: str
    added: datetime.datetime
    summary: Optional[str] = None
    log: Optional[TicketLog] = None


class User(ABC):
    def __init__(self, user_id):
        self.user_id = user_id

    def is_curator(self):
        return False

    def tickets(self):
        raise NotImplementedError

    def available_tickets(self):
        raise NotImplementedError

    def used_tickets(self):
        raise NotImplementedError

    def append_ticket(self, id=None, summary=None):
        raise NotImplementedError

    def log_ticket(self, ticket_id, request_id):
        raise NotImplementedError


class UserTest(User):
    def __init__(self, user_id, tickets=None, tickets_log=None):
        self.user_id = str(user_id)
        self._tickets = tickets or []
        self._tickets_log = tickets_log or []

    def tickets(self):
        return self._tickets

    def available_tickets(self):
        ticket_log_ids = [tl.ticket_id for tl in self._tickets_log]
        return [ticket for ticket in self._tickets if ticket.id not in ticket_log_ids]

    def used_tickets(self):
        ticket_log_ids = [tl.ticket_id for tl in self._tickets_log]
        return [ticket for ticket in self._tickets if ticket.id in ticket_log_ids]

    def append_ticket(self, id=None, summary=None):
        ticket = Ticket(
            id=id or 123,
            user_id=self.user_id,
            added=datetime.datetime.now(),
            summary=summary,
        )
        self._tickets.append(ticket)

    def log_ticket(self, ticket_id, request_id):
        ticket_log = TicketLog(
            ticket_id=ticket_id, request_id=request_id, added=datetime.datetime.now()
        )
        self._tickets_log.append(ticket_log)


class UserDB(User):
    def __init__(self, user_id, db_path):
        self._conn = sqlite3.connect(db_path)
        self._conn.set_trace_callback(logger.debug)
        self._conn.row_factory = sqlite3.Row
        self.user_id = str(user_id)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._conn.close()

    def tickets(self):
        sql = (
            "select * from verification_ticket left join verification_ticket_log on verification_ticket.id "
            "= verification_ticket_log.ticket_id where verification_ticket.user_id=?"
        )
        result = [
            dict(row) for row in self._conn.execute(sql, (self.user_id,)).fetchall()
        ]

        tickets = []
        for item in result:
            if item["ticket_id"] is not None:
                log = TicketLog(
                    ticket_id=item["ticket_id"],
                    request_id=item["request_id"],
                    added=item["added"],
                )
            else:
                log = None

            tickets.append(
                Ticket(
                    id=item["id"],
                    user_id=self.user_id,
                    added=item["added"],
                    summary=item["summary"],
                    log=log,
                )
            )

        return tickets

    def available_tickets(self):
        return [ticket for ticket in self.tickets() if ticket.log is None]

    def append_ticket(self, id=None, summary=None):
        self._conn.execute(
            "insert into verification_ticket (user_id,summary) values (?,?)",
            (self.user_id, summary),
        )
        self._conn.commit()

    def log_ticket(self, request_id):
        available_tickets = self.available_tickets()
        if not available_tickets:
            raise MissingPermission(
                "You don't have any available tickets to verify this request."
            )

        ticket = available_tickets[0]
        logger.debug("Using %s", ticket)

        self._conn.execute(
            "insert into verification_ticket_log (ticket_id,request_id) values (?,?)",
            (ticket.id, request_id),
        )
        self._conn.commit()

        return ticket
