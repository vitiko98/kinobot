from kinobot.request_trace import RequestTrace, get_not_passed, CheckerConfig
import os


async def trace_checks(ctx, trace: RequestTrace):
    configs = CheckerConfig.from_yaml_file(os.environ["TRACE_CONFIG"])
    not_passed = get_not_passed(trace, configs)
    found = False

    for item in not_passed:
        found = True
        await ctx.reply(
            f"***{item.name}***\n\n{item.description}\n\nPlease think twice before verifying this!"
        )

    return found
