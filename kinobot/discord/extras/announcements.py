from kinobot.db import sql_to_dict, KINOBASE
from kinobot.constants import DISCORD_ANNOUNCER_WEBHOOK
from kinobot.utils import send_webhook
from pydantic import BaseModel


class _Contributor(BaseModel):
    name: str
    records: int

    def line(self, n):
        return f"**{n}. {self.name}** - ***{self.records}*** collected tickets"


def top_contributors(db=None):
    sql = (
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
    str_ = f"## Top contributors - last 28 days\n\n{lines}"
    send_webhook(DISCORD_ANNOUNCER_WEBHOOK, str_)
