import asyncio
import datetime
import time

import aiohttp
import aiohttp_socks
import typing

import tibiapy
from tibiapy import abc, BoostedCreature, Category, Character, Forbidden, Guild, GuildWars, Highscores, House, \
    HouseOrder, \
    HouseStatus, \
    HouseType, KillStatistics, ListedGuild, ListedHouse, ListedNews, NetworkError, News, NewsCategory, NewsType, \
    Tournament, TournamentLeaderboard, VocationFilter, World, WorldOverview

__all__ = (
    "TibiaResponse",
    "Client",
)

# Tibia.com's cache for the community section is 5 minutes.
# This limit is not sent anywhere, so there's no way to automate it.
CACHE_LIMIT = 300

T = typing.TypeVar('T')


class TibiaResponse(typing.Generic[T], abc.Serializable):
    """Represents a response from Tibia.com

    Attributes
    ----------
    timestamp: :class:`datetime.datetime`
        The date and time when the page was fetched, in UTC.
    cached: :class:`bool`
        Whether the response is cached or it is a fresh response.
    age: :class:`int`
        The age of the cache in seconds.
    fetching_time: :class:`float`
        The time in seconds it took for Tibia.com to respond.
    parsing_time: :class:`float`
        The time in seconds it took for the response to be parsed into data.
    data: :class:`T`
        The data contained in the response.
    """
    def __init__(self, raw_response, data: T, parsing_time=None):
        self.timestamp = raw_response.timestamp  # type: datetime.datetime
        self.cached = raw_response.cached  # type: bool
        self.age = raw_response.age  # type: int
        self.fetching_time = raw_response.fetching_time
        self.parsing_time = parsing_time
        self.data = data

    __slots__ = (
        'timestamp',
        'cached',
        'age',
        'fetching_time',
        'parsing_time',
        'data',
    )

    @property
    def time_left(self):
        """:class:`datetime.timedelta`: The time left for the cache of this response to expire."""
        if not self.age:
            return datetime.timedelta()
        return datetime.timedelta(seconds=CACHE_LIMIT-self.age)-(datetime.datetime.utcnow()-self.timestamp)

    @property
    def seconds_left(self):
        """:class:`int`: The time left in seconds for this response's cache to expire."""
        return self.time_left.seconds


class RawResponse:
    def __init__(self, response: aiohttp.ClientResponse, fetching_time: float):
        self.timestamp = datetime.datetime.utcnow()
        self.fetching_time = fetching_time
        self.cached = response.headers.get("CF-Cache-Status") == "HIT"
        age = response.headers.get("Age")
        if age is not None and age.isnumeric():
            self.age = int(age)
        else:
            self.age = 0
        self.content = None


class Client:
    """An asynchronous client that fetches information from Tibia.com

    The client uses a :class:`aiohttp.ClientSession` to request the information.
    A single session is shared across all operations.

    If desired, a custom ClientSession instance may be passed, instead of creating a new one.

    .. versionadded:: 2.0.0

    .. versionchanged:: 3.0.0
        All methods return a :class:`TibiaResponse` instance, containing additional information such as cache age.

    Attributes
    ----------
    loop : :class:`asyncio.AbstractEventLoop`
        The event loop to use. The default one will be used if not defined.
    session: :class:`aiohttp.ClientSession`
        The client session that will be used for the requests. One will be created by default.
    proxy_url: :class:`str`
        The URL of the SOCKS proxy to use for requests.
        Note that if a session is passed, the SOCKS proxy won't be used and must be applied when creating the session.
    """

    def __init__(self, loop=None, session=None, *, proxy_url=None):
        self.loop = asyncio.get_event_loop() if loop is None else loop  # type: asyncio.AbstractEventLoop
        self._session_ready = asyncio.Event()
        if session is not None:
            self.session = session  # type: aiohttp.ClientSession
            self._session_ready.set()
        else:
            self.loop.create_task(self._initialize_session(proxy_url))

    async def _initialize_session(self, proxy_url=None):
        headers = {
            'User-Agent': "Tibia.py/%s (+https://github.com/Galarzaa90/tibia.py)" % tibiapy.__version__,
            'Accept-Encoding': "deflate, gzip"
        }
        connector = aiohttp_socks.SocksConnector.from_url(proxy_url) if proxy_url else None
        self.session = aiohttp.ClientSession(loop=self.loop, headers=headers,
                                             connector=connector)  # type: aiohttp.ClientSession
        self._session_ready.set()

    @classmethod
    def _handle_status(cls, status_code):
        """Handles error status codes, raising exceptions if necessary."""
        if status_code < 400:
            return
        if status_code == 403:
            raise Forbidden("403 Forbidden: Might be getting rate-limited")
        else:
            raise NetworkError("Request error, status code: %d" % status_code)

    async def _get(self, url):
        """Base GET request, handling possible error statuses.
        
        Parameters
        ----------
        url: :class:`str`
            The URL that will be requested.

        Returns
        -------
        :class:`str`
            The text content of the response.

        Raises
        ------
        Forbidden:
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        try:
            async with self.session.get(url, compress=True) as resp:
                self._handle_status(resp.status)
                return await resp.text()
        except aiohttp.ClientError as e:
            raise NetworkError("aiohttp.ClientError: %s" % e, e)
        except aiohttp_socks.SocksConnectionError as e:
            raise NetworkError("aiohttp_socks.SocksConnectionError: %s" % e, e)
        except UnicodeDecodeError as e:
            raise NetworkError('UnicodeDecodeError: %s' % e, e)

    async def _post(self, url, data):
        """Base POST request, handling possible error statuses.

        Parameters
        ----------
        url: :class:`str`
            The URL that will be requested.
        data: :class:`dict`
            A mapping representing the form-data to send as part of the request.

        Returns
        -------
        :class:`str`
            The text content of the response.
        """
        try:
            async with self.session.post(url, data=data) as resp:
                self._handle_status(resp.status)
                return await resp.text()
        except aiohttp.ClientError as e:
            raise NetworkError("aiohttp.ClientError: %s" % e, e)
        except aiohttp_socks.SocksConnectionError as e:
            raise NetworkError("aiohttp_socks.SocksConnectionError: %s" % e, e)
        except UnicodeDecodeError as e:
            raise NetworkError('UnicodeDecodeError: %s' % e, e)

    async def _request(self, method, url, data=None):
        """Base GET request, handling possible error statuses.

        Parameters
        ----------
        method: :class:`str`
            The HTTP method to use for the request.
        url: :class:`str`
            The URL that will be requested.
        data: :class:`dict`
            A mapping representing the form-data to send as part of the request.

        Returns
        -------
        :class:`RawResponse`
            The raw response obtained from the server.

        Raises
        ------
        Forbidden:
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        await self._session_ready.wait()
        try:
            init_time = time.perf_counter()
            async with self.session.request(method, url, data=data) as resp:
                self._handle_status(resp.status)
                response = RawResponse(resp, time.perf_counter()-init_time)
                response.content = await resp.text()
                return response
        except aiohttp.ClientError as e:
            raise NetworkError("aiohttp.ClientError: %s" % e, e)
        except aiohttp_socks.SocksConnectionError as e:
            raise NetworkError("aiohttp_socks.SocksConnectionError: %s" % e, e)
        except UnicodeDecodeError as e:
            raise NetworkError('UnicodeDecodeError: %s' % e, e)

    async def fetch_boosted_creature(self):
        """Fetches today's boosted creature.

        .. versionadded:: 2.1.0

        Returns
        -------
        :class:`TibiaResponse` of :class:`BoostedCreature`
            The boosted creature of the day.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", News.get_list_url())
        start_time = time.perf_counter()
        boosted_creature = BoostedCreature.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, boosted_creature, parsing_time)

    async def fetch_character(self, name):
        """Fetches a character by its name from Tibia.com

        Parameters
        ----------
        name: :class:`str`
            The name of the character.

        Returns
        -------
        :class:`TibiaResponse` of :class:`Character`
            A response containig the character, if found.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", Character.get_url(name.strip()))
        start_time = time.perf_counter()
        char = Character.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, char, parsing_time)

    async def fetch_guild(self, name):
        """Fetches a guild by its name from Tibia.com

        Parameters
        ----------
        name: :class:`str`
            The name of the guild. The case must match exactly.

        Returns
        -------
        :class:`TibiaResponse` of :class:`Guild`
            A response containing the found guild, if any.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", Guild.get_url(name))
        start_time = time.perf_counter()
        guild = Guild.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, guild, parsing_time)

    async def fetch_guild_wars(self, name):
        """Fetches a guild's wars by its name from Tibia.com

        Parameters
        ----------
        name: :class:`str`
            The name of the guild. The case must match exactly.

        Returns
        -------
        :class:`TibiaResponse` of :class:`GuildWars`
            A response containing the found guild's wars.

            If the guild doesn't exist, the displayed data will show a guild with no wars instead of indicating the
            guild doesn't exist.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", GuildWars.get_url(name))
        start_time = time.perf_counter()
        guild_wars = GuildWars.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, guild_wars, parsing_time)

    async def fetch_house(self, house_id, world):
        """Fetches a house in a specific world by its id.

        Parameters
        ----------
        house_id: :class:`int`
            The house's internal id.
        world: :class:`str`
            The name of the world to look for.

        Returns
        -------
        :class:`TibiaResponse` of :class:`House`
            The house if found, ``None`` otherwise.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", House.get_url(house_id, world))
        start_time = time.perf_counter()
        house = House.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, house, parsing_time)

    async def fetch_highscores_page(self, world, category=Category.EXPERIENCE,
                                    vocation=VocationFilter.ALL, page=1):
        """Fetches a single highscores page from Tibia.com

        Parameters
        ----------
        world: :class:`str`
            The world to search the highscores in.
        category: :class:`Category`
            The highscores category to search, by default Experience.
        vocation: :class:`VocationFilter`
            The vocation filter to use. No filter used by default.
        page: :class:`int`
            The page to fetch, by default the first page is fetched.

        Returns
        -------
        :class:`TibiaResponse` of :class:`Highscores`
            The highscores information or ``None`` if not found.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", Highscores.get_url(world, category, vocation, page))
        start_time = time.perf_counter()
        highscores = Highscores.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, highscores, parsing_time)

    async def fetch_kill_statistics(self, world):
        """Fetches the kill statistics of a world from Tibia.com.

        Parameters
        ----------
        world: :class:`str`
            The name of the world.

        Returns
        -------
        :class:`TibiaResponse` of :class:`KillStatistics`
            The kill statistics of the world if found.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", KillStatistics.get_url(world))
        start_time = time.perf_counter()
        kill_statistics = KillStatistics.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, kill_statistics, parsing_time)

    async def fetch_world(self, name):
        """Fetches a world from Tibia.com

        Parameters
        ----------
        name: :class:`str`
            The name of the world.

        Returns
        -------
        :class:`TibiaResponse` of :class:`World`
            A response containig the he world's information if found, ```None`` otherwise.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", World.get_url(name))
        start_time = time.perf_counter()
        world = World.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, world, parsing_time)

    async def fetch_world_houses(self, world, town, house_type=HouseType.HOUSE, status: HouseStatus = None,
                                 order=HouseOrder.NAME):
        """Fetches the house list of a world and type.

        Parameters
        ----------
        world: :class:`str`
            The name of the world.
        town: :class:`str`
            The name of the town.
        house_type: :class:`HouseType`
            The type of building. House by default.
        status: :class:`HouseStatus`, optional
            The house status to filter results. By default no filters will be applied.
        order: :class:`HouseOrder`, optional
            The ordering to use for the results. By default they are sorted by name.

        Returns
        -------
        :class:`TibiaResponse` of list of :class:`ListedHouse`
            A response containing the lists of houses meeting the criteria if found.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", ListedHouse.get_list_url(world, town, house_type, status, order))
        start_time = time.perf_counter()
        world_houses = ListedHouse.list_from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, world_houses, parsing_time)

    async def fetch_world_guilds(self, world: str):
        """Fetches the list of guilds in a world from Tibia.com

        Parameters
        ----------
        world: :class:`str`
            The name of the world.

        Returns
        -------
        :class:`TibiaResponse` of list of :class:`ListedGuild`
            A response containing the lists of guilds in the world.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", ListedGuild.get_world_list_url(world))
        start_time = time.perf_counter()
        guilds = ListedGuild.list_from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, guilds, parsing_time)

    async def fetch_world_list(self):
        """Fetches the world overview information from Tibia.com.

        Returns
        -------
        :class:`TibiaResponse` of :class:`WorldOverview`
            A response containing the world overview information.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", WorldOverview.get_url())
        start_time = time.perf_counter()
        world_overview = WorldOverview.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, world_overview, parsing_time)

    async def fetch_news_archive(self, begin_date, end_date, categories=None, types=None):
        """Fetches news from the archive meeting the search criteria.

        Parameters
        ----------
        begin_date: :class:`datetime.date`
            The beginning date to search dates in.
        end_date: :class:`datetime.date`
            The end date to search dates in.
        categories: `list` of :class:`NewsCategory`
            The allowed categories to show. If left blank, all categories will be searched.
        types : `list` of :class:`ListedNews`
            The allowed news types to show. if unused, all types will be searched.

        Returns
        -------
        :class:`TibiaResponse` of list of :class:`ListedNews`
            The news meeting the search criteria.

        Raises
        ------
        ValueError:
            If ``begin_date`` is more recent than ``end_date``.
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        if begin_date > end_date:
            raise ValueError("begin_date can't be more recent than end_date")
        if not categories:
            categories = list(NewsCategory)
        if not types:
            types = list(NewsType)
        data = {
            "filter_begin_day": begin_date.day,
            "filter_begin_month": begin_date.month,
            "filter_begin_year": begin_date.year,
            "filter_end_day": end_date.day,
            "filter_end_month": end_date.month,
            "filter_end_year": end_date.year,
        }
        for category in categories:
            key = "filter_%s" % category.value
            data[key] = category.value
        if NewsType.FEATURED_ARTICLE in types:
            data["filter_article"] = "article"
        if NewsType.NEWS in types:
            data["filter_news"] = "news"
        if NewsType.NEWS_TICKER in types:
            data["filter_ticker"] = "ticker"

        response = await self._request("post", News.get_list_url(), data)
        start_time = time.perf_counter()
        news = ListedNews.list_from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, news, parsing_time)

    async def fetch_recent_news(self, days=30, categories=None, types=None):
        """Fetches all the published news in the last specified days.

        This is a shortcut for :meth:`fetch_news_archive`, to handle dates more easily.

        Parameters
        ----------
        days: :class:`int`
            The number of days to search, by default 30.
        categories: `list` of :class:`NewsCategory`
            The allowed categories to show. If left blank, all categories will be searched.
        types : `list` of :class:`ListedNews`
            The allowed news types to show. if unused, all types will be searched.

        Returns
        -------
        :class:`TibiaResponse` of list of :class:`ListedNews`
            The news posted in the last specified days.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        end = datetime.date.today()
        begin = end - datetime.timedelta(days=days)
        return await self.fetch_news_archive(begin, end, categories, types)

    async def fetch_news(self, news_id):
        """Fetches a news entry by its id from Tibia.com

        Parameters
        ----------
        news_id: :class:`int`
            The id of the news entry.

        Returns
        -------
        :class:`TibiaResponse` of :class:`News`
            The news entry if found, ``None`` otherwise.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", News.get_url(news_id))
        start_time = time.perf_counter()
        news = News.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, news, parsing_time)

    async def fetch_tournament(self, tournament_cycle=0):
        """Fetches a tournament from Tibia.com

        Parameters
        ----------
        tournament_cycle: :class:`int`
            The cycle of the tournament. if unspecified, it will get the currently running tournament.

        Returns
        -------
        :class:`TibiaResponse` of :class:`Tournament`
            The tournament if found, ``None`` otherwise.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", Tournament.get_url(tournament_cycle))
        start_time = time.perf_counter()
        tournament = Tournament.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, tournament, parsing_time)

    async def fetch_tournament_leaderboard(self, tournament_cycle, world, page=1):
        """Fetches a tournament leaderboard from Tibia.com

        Parameters
        ----------
        tournament_cycle: :class:`int`
            The cycle of the tournament. if unspecified, it will get the currently running tournament.
        world: :class:`str`
            The name of the world to get the leaderboards for.
        page: :class:`int`
            The desired leaderboards page, by default 1 is used.

        Returns
        -------
        :class:`TibiaResponse` of :class:`TournamentLeaderboard`
            The tournament's leaderboard if found, ``None`` otherwise.

        Raises
        ------
        Forbidden
            If a 403 Forbidden error was returned.
            This usually means that Tibia.com is rate-limiting the client because of too many requests.
        NetworkError
            If there's any connection errors during the request.
        """
        response = await self._request("get", TournamentLeaderboard.get_url(world, tournament_cycle, page))
        start_time = time.perf_counter()
        tournament_leaderboard = TournamentLeaderboard.from_content(response.content)
        parsing_time = time.perf_counter() - start_time
        return TibiaResponse(response, tournament_leaderboard, parsing_time)
