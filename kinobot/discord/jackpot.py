from kinobot.config import config
from kinobot.infra import misc
from kinobot.misc import jackpot
from kinobot.utils import send_webhook
from kinobot.infra import misc as infra_misc


def _format_number(num: int) -> str:
    if num < 1000:
        return str(num)
    elif num < 1_000_000:
        return f"{num / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    elif num < 1_000_000_000:
        return f"{num / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    else:
        return f"{num / 1_000_000_000:.1f}".rstrip("0").rstrip(".") + "B"


def get_yearly_top(user_id, user_name):
    results = infra_misc.get_top_posts_by_impressions_current_year(user_id, limit=15)
    if not results:
        return None

    def _one_line(item):
        return f"{item.facebook_url} (**{_format_number(item.impressions)}** views)"

    lines = "\n".join([_one_line(i) for i in results])

    return f"{user_name}'s TOP POSTS from 2024\n\n{lines}"


def add_payout(user_id, amount):
    misc.add_payout(user_id, amount=amount)
    return misc.get_bonus_balance_dict(user_id)


def give_jackpot():
    def callback(jackpot, winner):
        misc.add_money_bonus(
            winner["user_id"], winner["id"], jackpot * 100, key="jackpot"
        )
        send_webhook(
            config.webhooks.announcer,
            f"**{winner['name']}** JUST WON YESTERDAY'S JACKPOT: **${round(jackpot, 3)}** 🤑",
        )

    jackpot.give(callback)


def get_current_jackpot():
    current = jackpot.get_current_day_jackpot()
    send_webhook(
        config.webhooks.announcer, f"Current day's jackpot: **${round(current, 3)}** 🤑"
    )
