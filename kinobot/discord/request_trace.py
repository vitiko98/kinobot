import os

from kinobot.request_trace import CheckerConfig
from kinobot.request_trace import get_not_passed
from kinobot.request_trace import RequestTrace
from kinobot.config import config


async def trace_checks(ctx, trace: RequestTrace):
    configs = CheckerConfig.from_yaml_file(config.trace_config)
    not_passed = get_not_passed(trace, configs)
    found = False

    for item in not_passed:
        found = True
        await ctx.reply(
            f"***{item.name}***\n\n{item.description}\n\nPlease think twice before verifying this!"
        )

    return found
