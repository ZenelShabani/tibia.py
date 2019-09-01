import datetime
import re
import urllib.parse
from collections import OrderedDict
from typing import List, Optional

import bs4

from tibiapy import abc
from tibiapy.enums import AccountStatus, Sex, Vocation
from tibiapy.errors import InvalidContent
from tibiapy.guild import Guild
from tibiapy.house import CharacterHouse
from tibiapy.utils import parse_json, parse_tibia_date, parse_tibia_datetime, parse_tibiacom_content, \
    parse_tibiadata_date, parse_tibiadata_datetime, try_datetime, try_enum

# Extracts the scheduled deletion date of a character."""
deleted_regexp = re.compile(r'([^,]+), will be deleted at (.*)')
# Extracts the death's level and killers.
death_regexp = re.compile(r'Level (?P<level>\d+) by (?P<killers>.*)\.</td>')
# From the killers list, filters out the assists.
death_assisted = re.compile(r'(?P<killers>.+)\.<br/>Assisted by (?P<assists>.+)')
# From a killer entry, extracts the summoned creature
death_summon = re.compile(r'(?P<summon>.+) of <a[^>]+>(?P<name>[^<]+)</a>')
# Extracts the contents of a tag
link_content = re.compile(r'>([^<]+)<')
# Extracts reason from TibiaData death
death_reason = re.compile(r'by (?P<killers>[^.]+)(?:\.\s+Assisted by (?P<assists>.+))?', re.DOTALL)

house_regexp = re.compile(r'paid until (.*)')
guild_regexp = re.compile(r'([\s\w()]+)\sof the\s(.+)')

title_regexp = re.compile(r'(.*)\((\d+) titles unlocked\)')
badge_popup_regexp = re.compile(r"\$\(this\),\s+'([^']+)',\s+'([^']+)',")

__all__ = (
    "AccountBadge",
    "AccountInformation",
    "Achievement",
    "Character",
    "Death",
    "GuildMembership",
    "Killer",
    "OtherCharacter",
    "OnlineCharacter",
)


class AccountBadge(abc.Serializable):
    """Represents an account badge.

    Attributes
    ----------
    name: :class:`str`
        The name of the badge.
    icon_url: :class:`str`
        The URL to the badge's icon URL.
    description: :class:`str`
        The description of the badge.
    """
    __slots__ = (
        "name",
        "icon_url",
        "description",
    )

    def __init__(self, name, icon_url, description):
        self.name = name  # type: str
        self.icon_url = icon_url  # type: str
        self.description = description  # type: str

    def __repr__(self):
        return "<%s name=%r description=%r>" % (self.__class__.__name__, self.name, self.description)


class AccountInformation(abc.Serializable):
    """Represents the account information of a character.

    Attributes
    ----------
    created: :class:`datetime.datetime`
        The date when the account was created.
    position: :class:`str`, optional
        The special position of this account, if any.
    loyalty_title: :class:`str`, optional
        The loyalty title of the account, if any.
    """
    __slots__ = (
        "created",
        "loyalty_title",
        "position",
    )

    def __init__(self, created, loyalty_title=None, position=None):
        self.created = try_datetime(created)
        self.loyalty_title = loyalty_title  # type: Optional[str]
        self.position = position  # type: Optional[str]

    def __repr__(self):
        return "<%s created=%r>" % (self.__class__.__name__, self.created)


class Achievement(abc.Serializable):
    """Represents an achievement listed on a character's page.

    Attributes
    ----------
    name: :class:`str`
        The name of the achievement.
    grade: :class:`int`
        The grade of the achievement, also known as stars.
    secret: :class:´bool´
        Whether the achievement is secret or not.
    """
    __slots__ = (
        "name",
        "grade",
        "secret",
    )

    def __init__(self, name, grade, secret = False):
        self.name = name   # type: str
        self.grade = int(grade)
        self.secret = secret

    def __repr__(self):
        return "<%s name=%r grade=%d secret=%s>" % (self.__class__.__name__, self.name, self.grade, self.secret)


class Character(abc.BaseCharacter):
    """Represents a Tibia character.

    Attributes
    ----------
    name: :class:`str`
        The name of the character.
    deletion_date: :class:`datetime.datetime`, optional
        The date when the character will be deleted if it is scheduled for deletion.
    former_names: :class:`list` of :class:`str`
        Previous names of the character.
    title: :class:`str`, optional
        The character's selected title, if any.
    unlocked_titles: :class:`int`
        The number of titles the character has unlocked.
    sex: :class:`Sex`
        The character's sex.
    vocation: :class:`Vocation`
        The character's vocation.
    level: :class:`int`
        The character's level.
    achievement_points: :class:`int`
        The total of achievement points the character has.
    world: :class:`str`
        The character's current world.
    former_world: :class:`str`, optional
        The previous world the character was in, in the last 6 months.
    residence: :class:`str`
        The current hometown of the character.
    married_to: :class:`str`, optional
        The name of the character's spouse.
    house: :class:`CharacterHouse`, optional
        The house currently owned by the character.
    guild_membership: :class:`GuildMembership`, optional
        The guild the character is a member of.
    last_login: :class:`datetime.datetime`, optional
        The last time the character logged in. It will be ``None`` if the character has never logged in.
    position: :class:`str`, optional
        The position of the character (e.g. CipSoft Member), if any.
    comment: :class:`str`, optional
        The displayed comment.
    account_status: :class:`AccountStatus`
        Whether the character's account is Premium or Free.
    account_badges: :class:`list` of :class:`AccountBadge`
        The displayed account badges.
    achievements: :class:`list` of :class:`Achievement`
        The achievements chosen to be displayed.
    deaths: :class:`list` of :class:`Death`
        The character's recent deaths.
    account_information: :class:`AccountInformation`, optional
        The character's account information, if visible.
    other_characters: :class:`list` of :class:`OtherCharacter`
        Other characters in the same account.
        It will be empty if the character is hidden, otherwise, it will contain at least the character itself.
    """
    __slots__ = (
        "former_names",
        "sex",
        "title",
        "unlocked_titles",
        "vocation",
        "level",
        "achievement_points",
        "world",
        "former_world",
        "residence",
        "married_to",
        "house",
        "guild_membership",
        "last_login",
        "account_status",
        "position",
        "comment",
        "account_badges",
        "achievements",
        "deaths",
        "account_information",
        "other_characters",
        "deletion_date",
    )

    def __init__(self, name=None, world=None, vocation=None, level=0, sex=None, **kwargs):
        self.name = name  # type: str
        self.former_names = kwargs.get("former_names", [])  # type: List[str]
        self.title = kwargs.get("title")  # type: Optional[str]
        self.unlocked_titles = int(kwargs.get("unlocked_titles", 0))
        self.sex = try_enum(Sex, sex)
        self.vocation = try_enum(Vocation, vocation)
        self.level = int(level)
        self.achievement_points = int(kwargs.get("achievement_points", 0))
        self.world = world  # type: str
        self.former_world = kwargs.get("former_world")  # type: Optional[str]
        self.residence = kwargs.get("residence")  # type: str
        self.married_to = kwargs.get("married_to")  # type: Optional[str]
        self.house = kwargs.get("house")  # type: Optional[CharacterHouse]
        self.guild_membership = kwargs.get("guild_membership")  # type: Optional[GuildMembership]
        self.last_login = try_datetime(kwargs.get("last_login"))
        self.account_status = try_enum(AccountStatus, kwargs.get("account_status"))
        self.position = kwargs.get("position")  # type: Optional[str]
        self.comment = kwargs.get("comment")  # type: Optional[str]
        self.account_badges = kwargs.get("account_badges", [])  # type: List[AccountBadge]
        self.achievements = kwargs.get("achievements", [])  # type: List[Achievement]
        self.deaths = kwargs.get("deaths", [])  # type: List[Death]
        self.account_information = kwargs.get("account_information")  # type: Optional[AccountInformation]
        self.other_characters = kwargs.get("other_characters", [])  # type: List[OtherCharacter]
        self.deletion_date = try_datetime(kwargs.get("deletion_date"))

    # region Properties
    @property
    def deleted(self) -> bool:
        """:class:`bool`: Whether the character is scheduled for deletion or not."""
        return self.deletion_date is not None

    @property
    def guild_name(self) -> Optional[str]:
        """:class:`str`: The name of the guild the character belongs to, or ``None``."""
        return self.guild_membership.name if self.guild_membership else None

    @property
    def guild_rank(self) -> Optional[str]:
        """:class:`str`: The character's rank in the guild they belong to, or ``None``."""
        return self.guild_membership.rank if self.guild_membership else None

    @property
    def guild_url(self):
        """:class:`str`: The character's rank in the guild they belong to, or ``None``."""
        return Guild.get_url(self.guild_membership.name) if self.guild_membership else None

    @property
    def hidden(self):
        """:class:`bool`: Whether this is a hidden character or not."""
        return len(self.other_characters) == 0

    @property
    def married_to_url(self):
        """:class:`str`: The URL to the husband/spouse information page on Tibia.com, if applicable."""
        return self.get_url(self.married_to) if self.married_to else None
    # endregion

    # region Public methods
    @classmethod
    def from_content(cls, content):
        """Creates an instance of the class from the html content of the character's page.

        Parameters
        ----------
        content: :class:`str`
            The HTML content of the page.

        Returns
        -------
        :class:`Character`
            The character contained in the page, or None if the character doesn't exist

        Raises
        ------
        InvalidContent
            If content is not the HTML of a character's page.
        """
        parsed_content = parse_tibiacom_content(content)
        tables = cls._parse_tables(parsed_content)
        char = Character()
        if "Could not find character" in tables.keys():
            return None
        if "Character Information" in tables.keys():
            char._parse_character_information(tables["Character Information"])
        else:
            raise InvalidContent("content does not contain a tibia.com character information page.")
        char._parse_achievements(tables.get("Account Achievements", []))
        if "Account Badges" in tables:
            char._parse_badges(tables["Account Badges"])
        char._parse_deaths(tables.get("Character Deaths", []))
        char._parse_account_information(tables.get("Account Information", []))
        char._parse_other_characters(tables.get("Characters", []))
        return char

    @classmethod
    def from_tibiadata(cls, content):
        """Builds a character object from a TibiaData character response.

        Parameters
        ----------
        content: :class:`str`
            The JSON content of the response.

        Returns
        -------
        :class:`Character`
            The character contained in the page, or None if the character doesn't exist

        Raises
        ------
        InvalidContent
            If content is not a JSON string of the Character response."""
        json_content = parse_json(content)
        char = cls()
        try:
            character = json_content["characters"]
            if "error" in character:
                return None
            character_data = character["data"]
            char.name = character_data["name"]
            char.world = character_data["world"]
            char.level = character_data["level"]
            char.achievement_points = character_data["achievement_points"]
            char.sex = try_enum(Sex, character_data["sex"])
            char.vocation = try_enum(Vocation, character_data["vocation"])
            char.residence = character_data["residence"]
            char.account_status = try_enum(AccountStatus, character_data["account_status"])
        except KeyError:
            raise InvalidContent("content does not match a character json from TibiaData.")
        char.former_names = character_data.get("former_names", [])
        if "deleted" in character_data:
            char.deletion_date = parse_tibiadata_datetime(character_data["deleted"])
        char.married_to = character_data.get("married_to")
        char.former_world = character_data.get("former_world")
        char.position = character_data.get("Position:")
        if "guild" in character_data:
            char.guild_membership = GuildMembership(character_data["guild"]["name"], character_data["guild"]["rank"])
        if "house" in character_data:
            house = character_data["house"]
            paid_until_date = parse_tibiadata_date(house["paid"])
            char.house = CharacterHouse(house["houseid"], house["name"], char.world, house["town"], char.name,
                                        paid_until_date)
        char.comment = character_data.get("comment")
        if len(character_data["last_login"]) > 0:
            char.last_login = parse_tibiadata_datetime(character_data["last_login"][0])
        for achievement in character["achievements"]:
            char.achievements.append(Achievement(achievement["name"], achievement["stars"]))

        char._parse_deaths_tibiadata(character.get("deaths", []))

        for other_char in character["other_characters"]:
            char.other_characters.append(OtherCharacter(other_char["name"], other_char["world"],
                                                        other_char["status"] == "online",
                                                        other_char["status"] == "deleted"))

        if character["account_information"]:
            acc_info = character["account_information"]
            created = parse_tibiadata_datetime(acc_info.get("created"))
            loyalty_title = None if acc_info["loyalty_title"] == "(no title)" else acc_info["loyalty_title"]
            position = acc_info.get("position")

            char.account_information = AccountInformation(created, loyalty_title, position)

        return char
    # endregion

    # region Private methods
    def _parse_account_information(self, rows):
        """
        Parses the character's account information

        Parameters
        ----------
        rows: :class:`list` of :class:`bs4.Tag`, optional
            A list of all rows contained in the table.
        """
        acc_info = {}
        if not rows:
            return
        for row in rows:
            cols_raw = row.find_all('td')
            cols = [ele.text.strip() for ele in cols_raw]
            field, value = cols
            field = field.replace("\xa0", "_").replace(" ", "_").replace(":", "").lower()
            value = value.replace("\xa0", " ")
            acc_info[field] = value
        created = parse_tibia_datetime(acc_info["created"])
        loyalty_title = None if acc_info["loyalty_title"] == "(no title)" else acc_info["loyalty_title"]
        position = acc_info.get("position")
        self.account_information = AccountInformation(created, loyalty_title, position)

    def _parse_achievements(self, rows):
        """
        Parses the character's displayed achievements

        Parameters
        ----------
        rows: :class:`list` of :class:`bs4.Tag`
            A list of all rows contained in the table.
        """
        for row in rows:
            cols = row.find_all('td')
            if len(cols) != 2:
                continue
            field, value = cols
            grade = str(field).count("achievement-grade-symbol")
            name = value.text.strip()
            secret_image = value.find("img")
            secret = False
            if secret_image:
                secret = True
            self.achievements.append(Achievement(name, grade, secret))

    def _parse_badges(self, rows):
        """
        Parses the character's displayed badges

        Parameters
        ----------
        rows: :class:`list` of :class:`bs4.Tag`
            A list of all rows contained in the table.
        """
        row = rows[0]
        columns = row.find_all('td')
        for column in columns:
            popup = column.find("span", attrs={"class": "HelperDivIndicator"})
            if not popup:
                # Badges are visible, but none selected.
                return
            m = badge_popup_regexp.search(popup['onmouseover'])
            if m:
                name = m.group(1)
                description = m.group(2)
            else:
                continue
            icon_image = column.find("img")
            icon_url = icon_image['src']
            self.account_badges.append(AccountBadge(name, icon_url, description))

    def _parse_character_information(self, rows):
        """
        Parses the character's basic information and applies the found values.

        Parameters
        ----------
        rows: :class:`list` of :class:`bs4.Tag`
            A list of all rows contained in the table.
        """
        int_rows = ["level", "achievement_points"]
        char = {}
        house = {}
        for row in rows:
            cols_raw = row.find_all('td')
            cols = [ele.text.strip() for ele in cols_raw]
            field, value = cols
            field = field.replace("\xa0", "_").replace(" ", "_").replace(":", "").lower()
            value = value.replace("\xa0", " ")
            # This is a special case cause we need to see the link
            if field == "house":
                house_text = value
                paid_until = house_regexp.search(house_text).group(1)
                paid_until_date = parse_tibia_date(paid_until)
                house_link = cols_raw[1].find('a')
                url = urllib.parse.urlparse(house_link["href"])
                query = urllib.parse.parse_qs(url.query)
                house = {"id": int(query["houseid"][0]), "name": house_link.text.strip(),
                         "town": query["town"][0], "paid_until": paid_until_date}
                continue
            if field in int_rows:
                value = int(value)
            char[field] = value

        # If the character is deleted, the information is fouund with the name, so we must clean it
        m = deleted_regexp.match(char["name"])
        if m:
            char["name"] = m.group(1)
            char["deletion_date"] = parse_tibia_datetime(m.group(2))
        if "guild_membership" in char:
            m = guild_regexp.match(char["guild_membership"])
            char["guild_membership"] = GuildMembership(m.group(2), m.group(1))

        if "former_names" in char:
            former_names = [fn.strip() for fn in char["former_names"].split(",")]
            char["former_names"] = former_names

        if "never" in char["last_login"]:
            char["last_login"] = None
        else:
            char["last_login"] = parse_tibia_datetime(char["last_login"])

        m = title_regexp.match(char.get("title", ""))
        if m:
            name = m.group(1).strip()
            unlocked = int(m.group(2))
            if name == "None":
                name = None
            char["title"] = name
            char["unlocked_titles"] = unlocked

        char["vocation"] = try_enum(Vocation, char["vocation"])
        char["sex"] = try_enum(Sex, char["sex"])
        char["account_status"] = try_enum(AccountStatus, char["account_status"])

        for k, v in char.items():
            try:
                setattr(self, k, v)
            except AttributeError:
                # This means that there is a attribute in the character's information table that does not have a
                # corresponding class attribute.
                pass
        if house:
            self.house = CharacterHouse(house["id"], house["name"], self.world, house["town"], self.name,
                                        house["paid_until"])

    def _parse_deaths(self, rows):
        """
        Parses the character's recent deaths

        Parameters
        ----------
        rows: :class:`list` of :class:`bs4.Tag`
            A list of all rows contained in the table.
        """
        for row in rows:
            cols = row.find_all('td')
            death_time_str = cols[0].text.replace("\xa0", " ").strip()
            death_time = parse_tibia_datetime(death_time_str)
            death = str(cols[1]).replace("\xa0", " ")
            death_info = death_regexp.search(death)
            if death_info:
                level = int(death_info.group("level"))
                killers_desc = death_info.group("killers")
            else:
                continue
            death = Death(self.name, level, time=death_time)
            assists_name_list = []
            # Check if the killers list contains assists
            assist_match = death_assisted.search(killers_desc)
            if assist_match:
                # Filter out assists
                killers_desc = assist_match.group("killers")
                # Split assists into a list.
                assists_name_list = self._split_list(assist_match.group("assists"))
            killers_name_list = self._split_list(killers_desc)
            for killer in killers_name_list:
                killer_dict = self._parse_killer(killer)
                death.killers.append(Killer(**killer_dict))
            for assist in assists_name_list:
                # Extract names from character links in assists list.
                assist_dict = {"name": link_content.search(assist).group(1), "player": True}
                death.assists.append(Killer(**assist_dict))
            try:
                self.deaths.append(death)
            except ValueError:
                # Some pvp deaths have no level, so they are raising a ValueError, they will be ignored for now.
                continue

    def _parse_deaths_tibiadata(self, deaths):
        for death in deaths:
            level = death["level"]
            death_time = parse_tibiadata_datetime(death["date"])
            m = death_reason.search(death["reason"])
            _death = Death(self.name, level, time=death_time)
            killers_str = []
            assists_str = []
            involved = [i["name"] for i in death["involved"]]
            if m and m.group("killers"):
                killers_str = [k.strip() for k in self._split_list(m.group("killers").strip())]
            if m and m.group("assists"):
                assists_str = [a.strip() for a in self._split_list(m.group("assists").strip())]
            for killer in killers_str:
                summoner = next((i for i in involved if "of %s" % i in killer), None)
                summon = None
                if summoner:
                    summon = killer.replace(" of %s" % summoner, "")
                    killer = summoner
                _death.killers.append(Killer(killer, killer in involved, summon=summon))
            for assist in assists_str:
                _death.assists.append(Killer(assist, assist in involved))
            self.deaths.append(_death)

    @classmethod
    def _parse_killer(cls, killer):
        """Parses a killer into a dictionary.

        Parameters
        ----------
        killer: :class:`str`
            The killer's raw HTML string.

        Returns
        -------
        :class:`dict`: A dictionary containing the killer's info.
        """
        # If the killer contains a link, it is a player.
        if "href" in killer:
            killer_dict = {"name": link_content.search(killer).group(1), "player": True}
        else:
            killer_dict = {"name": killer, "player": False}
        # Check if it contains a summon.
        m = death_summon.search(killer)
        if m:
            killer_dict["summon"] = m.group("summon")
        return killer_dict

    def _parse_other_characters(self, rows):
        """
        Parses the character's other visible characters.

        Parameters
        ----------
        rows: :class:`list` of :class:`bs4.Tag`
            A list of all rows contained in the table.
        """
        for row in rows:
            cols_raw = row.find_all('td')
            cols = [ele.text.strip() for ele in cols_raw]
            if len(cols) != 5:
                continue
            name, world, status, __, __ = cols
            name = name.replace("\xa0", " ").split(". ")[1]
            main_img = cols_raw[0].find('img')
            main = False
            if main_img and main_img['title'] == "Main Character":
                main = True
            self.other_characters.append(OtherCharacter(name, world, status == "online", status == "deleted", main))

    @classmethod
    def _parse_tables(cls, parsed_content):
        """
        Parses the information tables contained in a character's page.

        Parameters
        ----------
        parsed_content: :class:`bs4.BeautifulSoup`
            A :class:`BeautifulSoup` object containing all the content.

        Returns
        -------
        :class:`OrderedDict`[str, :class:`list`of :class:`bs4.Tag`]
            A dictionary containing all the table rows, with the table headers as keys.
        """
        tables = parsed_content.find_all('table', attrs={"width": "100%"})
        output = OrderedDict()
        for table in tables:
            title = table.find("td").text
            output[title] = table.find_all("tr")[1:]
        return output

    # Todo: This might be turned into a function if it's needed elsewhere
    @classmethod
    def _split_list(cls, items, separator=",", last_separator=" and "):
        """
        Splits a string listing elements into an actual list.

        Parameters
        ----------
        items: :class:`str`
            A string listing elements.
        separator: :class:`str`
            The separator between each item. A comma by default.
        last_separator: :class:`str`
            The separator used for the last item. ' and ' by default.

        Returns
        -------
        :class:`list` of :class:`str`
            A list containing each one of the items.
        """
        if items is None:
            return None
        items = items.split(separator)
        last_item = items[-1]
        last_split = last_item.split(last_separator)
        if len(last_split) > 1:
            items[-1] = last_split[0]
            items.append(last_split[1])
        return [e.strip() for e in items]
    # endregion


class Death(abc.Serializable):
    """
    Represents a death by a character

    Attributes
    -----------
    name: :class:`str`
        The name of the character this death belongs to.
    level: :class:`int`
        The level at which the death occurred.
    killers: :class:`list` of :class:`Killer`
        A list of all the killers involved.
    assists: :class:`list` of :class:`Killer`
        A list of characters that were involved, without dealing damage.
    time: :class:`datetime.datetime`
        The time at which the death occurred.
    """
    __slots__ = (
        "level",
        "killers",
        "time",
        "assists",
        "name")

    def __init__(self, name=None, level=0, **kwargs):
        self.name = name
        self.level = level
        self.killers = kwargs.get("killers", [])  # type: List[Killer]
        self.assists = kwargs.get("assists", [])  # type: List[Killer]
        self.time = try_datetime(kwargs.get("time"))

    def __repr__(self):
        attributes = ""
        for attr in self.__slots__:
            if attr in ["name", "level"]:
                continue
            v = getattr(self, attr)
            if isinstance(v, int) and v == 0 and not isinstance(v, bool):
                continue
            if isinstance(v, list) and len(v) == 0:
                continue
            if v is None:
                continue
            attributes += ",%s=%r" % (attr, v)
        return "{0.__class__.__name__}({0.name!r},{0.level!r}{1})".format(self, attributes)

    @property
    def by_player(self):
        """:class:`bool`: Whether the kill involves other characters."""
        return any([k.player and self.name != k.name for k in self.killers])

    @property
    def killer(self):
        """:class:`Killer`: The first killer in the list.

        This is usually the killer that gave the killing blow."""
        return self.killers[0] if self.killers else None


class GuildMembership(abc.BaseGuild):
    """
    Represents the guild information of a character.

    Attributes
    ----------
    name: :class:`str`
        The name of the guild.
    rank: :class:`str`
        The name of the rank the member has.
    """
    __slots__ = (
        "rank",
    )

    def __init__(self, name, rank):
        self.name = name  # type: str
        self.rank = rank  # type: str

    def __repr__(self):
        return "<{0.__class__.__name__} name={0.name!r} rank={0.rank!r}>".format(self)


class Killer(abc.Serializable):
    """
    Represents a killer.

    A killer can be:

    a) A creature.
    b) A character.
    c) A creature summoned by a character.

    Attributes
    -----------
    name: :class:`str`
        The name of the killer. In the case of summons, the name belongs to the owner.
    player: :class:`bool`
        Whether the killer is a player or not.
    summon: :class:`str`, optional
        The name of the summoned creature, if applicable.
    """
    __slots__ = (
        "name",
        "player",
        "summon"
    )

    def __init__(self, name, player=False, summon=None):
        self.name = name  # type: str
        self.player = player  # type: bool
        self.summon = summon  # type: Optional[str]

    def __repr__(self):
        attributes = ""
        for attr in self.__slots__:
            if attr in ["name"]:
                continue
            v = getattr(self, attr)
            if isinstance(v, int) and v == 0 and not isinstance(v, bool):
                continue
            if isinstance(v, list) and len(v) == 0:
                continue
            if v is None:
                continue
            attributes += ",%s=%r" % (attr, v)
        return "{0.__class__.__name__}({0.name!r}{1})".format(self, attributes)

    @property
    def url(self):
        """
        :class:`str`, optional: The URL of the character’s information page on Tibia.com, if applicable.
        """
        return Character.get_url(self.name) if self.player else None


class OnlineCharacter(abc.BaseCharacter):
    """
    Represents an online character.

    Attributes
    ----------
    name: :class:`str`
        The name of the character.
    world: :class:`str`
        The name of the world.
    vocation: :class:`Vocation`
        The vocation of the character.
    level: :class:`int`
        The level of the character.
    """
    __slots__ = (
        "world",
        "vocation",
        "level",
    )

    def __init__(self, name, world, level, vocation):
        self.name = name  # type: str
        self.world = world  # type: str
        self.level = int(level)
        self.vocation = try_enum(Vocation, vocation)


class OtherCharacter(abc.BaseCharacter):
    """
    Represents other characters displayed in the Character's information page.

    Attributes
    ----------
    name: :class:`str`
        The name of the character.
    world: :class:`str`
        The name of the world.
    online: :class:`bool`
        Whether the character is online or not.
    deleted: :class:`bool`
        Whether the character is scheduled for deletion or not.
    main: :class:`bool`
        Whether this is the main character or not.
    """
    __slots__ = (
        "world",
        "online",
        "deleted",
        "main",
    )

    def __init__(self, name, world, online=False, deleted=False, main=False):
        self.name = name  # type: str
        self.world = world  # type: str
        self.online = online  # type: bool
        self.deleted = deleted  # type: bool
        self.main = main  # type: bool

