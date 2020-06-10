import asyncio
import datetime
import logging
import random

import tibiapy

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('[%(asctime)s][%(levelname)s] %(message)s'))

log = logging.getLogger("tibia.py")
log.setLevel(logging.INFO)
log.addHandler(console_handler)


async def main():
    log.info("Initializing client")
    client = tibiapy.Client()
    try:
        log.info("Fetching world list...")
        response = await client.fetch_world_list()
        assert isinstance(response, tibiapy.TibiaResponse)
        assert isinstance(response.data, tibiapy.WorldOverview)
        log.info("{} worlds found.".format(len(response.data.worlds)))
        assert isinstance(response.data.record_count, int)
        assert response.data.record_count > 0
        assert isinstance(response.data.record_date, datetime.datetime)

        selected = random.choice(response.data.worlds)
        assert isinstance(selected, tibiapy.ListedWorld)
        log.info("World {0.name} selected: {0.online_count} online | {0.pvp_type} | {0.location}".format(selected))
        assert isinstance(selected.pvp_type, tibiapy.PvpType)
        assert isinstance(selected.location, tibiapy.WorldLocation)
        log.info("Fetching world...")
        world = await client.fetch_world(selected.name)


    finally:
        await client.session.close()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())