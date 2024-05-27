import logging

from discord_webhook import DiscordEmbed
from discord_webhook import DiscordWebhook

from .db import RequestRepository
from .events import PostCreated

logger = logging.getLogger(__name__)


publishers = {}


def register(key):
    def decorator(cls):
        publishers[key] = cls
        return cls

    return decorator


@register("post_webhooks")
class PostCreatedWebhooks:
    def __init__(self, urls=None) -> None:
        self._urls = urls or []

    def _get_embed(self, post_created: PostCreated):
        embed = DiscordEmbed(
            title=f"by {post_created.request.user.name}",
            description=post_created.request.content[:500],
        )
        embed.set_author(name="Instagram post", url=post_created.permalink)
        embed.set_image(url=post_created.finished_request.image_uris[0])
        embed.set_timestamp()
        return embed

    def __call__(self, post_created: PostCreated):
        embed = self._get_embed(post_created)

        for url in self._urls:
            try:
                wh = DiscordWebhook(url=url)
                wh.add_embed(embed)
                wh.execute()
            except Exception as error:
                logger.error(error)


@register("post_register")
class RegisterPost:
    def __init__(self, repository: RequestRepository) -> None:
        self._repository = repository

    def __call__(self, post_created: PostCreated):
        self._repository.post(post_created.ig_id, post_created.request.id)


@register("post_quarantine")
class QuarantineRequest:
    def __init__(self, repository: RequestRepository) -> None:
        self._repository = repository

    def __call__(self, post_created: PostCreated):
        self._repository.quarantine(post_created.request.id)
