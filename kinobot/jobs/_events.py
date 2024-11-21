from dataclasses import dataclass
from dataclasses import field
import datetime
import logging
from typing import Optional

from kinobot.config import config
from kinobot.misc import bonus
from kinobot.infra import misc as infra_misc
from kinobot.utils import send_webhook

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NoRequestsFound:
    name: str
    tag: Optional[str] = None
    dt: datetime.datetime = field(default_factory=datetime.datetime.now)


@dataclass(frozen=True)
class RequestPosted:
    request_id: str
    user_id: str
    user_name: str
    post_id: str
    url: str
    single_image: bool
    dimensions: tuple
    dt: datetime.datetime = field(default_factory=datetime.datetime.now)


### Specific handlers
def _send_webhook(msg, images=None):
    send_webhook(config.post_events.webhook, msg, images=images)


def _cents_to_dollar(cents):
    dollars = cents / 100
    return "${:,.2f}".format(dollars)


def _give_money_bonus(r: RequestPosted):
    amount = config.post_events.money_bonus
    msg = "Regular"
    if r.single_image and r.dimensions[0] / r.dimensions[1] <= 1.0:
        amount = config.post_events.money_bonus_plus
        msg = "Single image - non-wide, large"

    infra_misc.add_money_bonus(r.user_id, r.post_id, amount)
    balance = infra_misc.get_bonus_balance(r.user_id)
    _send_webhook(
        f"*{r.user_name}* received **{_cents_to_dollar(amount)}** ({msg} BONUS) [post: {r.post_id}]\nNew balance: **{_cents_to_dollar(balance)}** 🤑"
    )


def _give_bonus(r: RequestPosted):
    gbs_ = float(config.post_events.gb_bonus)

    bonus.give_gbs(r.user_id, gbs_)

    _send_webhook(
        f"*{r.user_name}* received **{gbs_} GBs** (current post bonus) [post: {r.post_id}]"
    )


_events_map = {RequestPosted: [_give_money_bonus]}


def handler(event):
    logger.debug("Handling event: %s", event)
    try:
        event_handlers = _events_map[type(event)]
        logger.debug("Handler: %s", event_handlers)
    except KeyError:
        logger.debug("No event handler found for %s", event)
        return None

    for handler_ in event_handlers:
        try:
            handler_(event)
        except Exception as error:
            logger.exception(error)
        else:
            logger.debug("%s OK", handler_)
