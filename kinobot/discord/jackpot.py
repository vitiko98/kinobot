from kinobot.config import config
from kinobot.infra import misc
from kinobot.misc import jackpot
from kinobot.utils import send_webhook


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
