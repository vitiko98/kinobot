from pydantic import BaseModel

from kinobot.config import config
from kinobot.db import KINOBASE
from kinobot.db import sql_to_dict
from kinobot.utils import send_webhook


class _Contributor(BaseModel):
    name: str
    records: int

    def line(self, n):
        return f"**{n}. {self.name}** - ***{self.records}*** active tickets"


def top_contributors(db=None):
    sql = (
        "select users.name, users.id, count(*) as records from verification_ticket left "
        "join verification_ticket_log on verification_ticket.id = verification_ticket_log.ticket_id "
        "left join users on verification_ticket.user_id=users.id where datetime(verification_ticket.added, "
        "'+' || verification_ticket.days_expires_in || ' days') >= datetime('now') group by users.id order by records desc;"
    )
    sql_ = (
        "select users.name, count(*) as records from verification_ticket "
        "left join users on verification_ticket.user_id = users.id where "
        "verification_ticket.added >= DATE('now', '-28 day') group by users.name order by records desc;"
    )
    result = sql_to_dict(db or KINOBASE, sql)[:7]
    if not result:
        return None
    lines = "\n".join(
        [_Contributor(**item).line(n) for n, item in enumerate(result, start=1)]
    )
    str_ = f"## Top active tickets\n\n{lines}"
    send_webhook(config.webhook.announcer, str_)
