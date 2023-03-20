import argparse
import asyncio
import math
import traceback
from copy import deepcopy
from typing import Tuple, Coroutine

from couchdb import Database
from furl import furl, urllib
from telegram import Update, InlineKeyboardButton, InputMediaPhoto, Message
from telegram._utils.defaultvalue import DEFAULT_NONE
from telegram._utils.types import ReplyMarkup, ODVInput
from telegram.error import RetryAfter, BadRequest
from telegram.ext import CommandHandler, CallbackContext, ConversationHandler, CallbackQueryHandler, MessageHandler, Application, filters

from BotNotificator import updatePublicChannel, notifyUsersAboutNewCoupons, ChannelUpdateMode, nukeChannel, cleanupChannel, notifyUsersAboutUpcomingAccountDeletion
from BotUtils import *
from BaseUtils import *
from BotUtils import loadConfig, ImageCache

from Helper import *
from Crawler import BKCrawler, UserStats

from UtilsCouponsDB import Coupon, User, ChannelCoupon, InfoEntry, getCouponsSeparatedByType, CouponFilter, UserFavoritesInfo, \
    USER_SETTINGS_ON_OFF, CouponViews, sortCouponsAsList, MAX_HOURS_ACTIVITY_TRACKING, getCouponViewByIndex
from CouponCategory import CouponCategory
from Helper import BotAllowedCouponTypes, CouponType
from UtilsOffers import offerGetImagePath


class CouponCallbackVars:
    ALL_COUPONS = f"?a=dcs&m={CouponViews.ALL.getViewCode()}&cs="
    ALL_COUPONS_WITHOUT_MENU = f"?a=dcs&m={CouponViews.ALL_WITHOUT_MENU.getViewCode()}&cs="
    MEAT_WITHOUT_PLANT_BASED = f"?a=dcs&m={CouponViews.MEAT_WITHOUT_PLANT_BASED.getViewCode()}&cs="
    VEGGIE = f"?a=dcs&m={CouponViews.VEGGIE.getViewCode()}&cs="
    # MEAT_WITHOUT_PLANT_BASED = f"?a=dcs&m={CouponDisplayMode.MEAT_WITHOUT_PLANT_BASED}&cs="
    FAVORITES = f"?a=dcs&m={CouponViews.FAVORITES.getViewCode()}&cs="


class CallbackPattern:
    DISPLAY_COUPONS = '.*a=dcs.*'


def generateCallbackRegEx(settings: dict):
    # Generates one CallBack RegEx for a set of settings.
    settingsCallbackRegEx = '^'
    index = 0
    for settingsKey in settings:
        isLastSetting = index == len(settings) - 1
        settingsCallbackRegEx += settingsKey
        if not isLastSetting:
            settingsCallbackRegEx += '|'
        index += 1
    settingsCallbackRegEx += '$'
    return settingsCallbackRegEx


MAX_CACHE_AGE_SECONDS = 7 * 24 * 60 * 60


async def cleanupCache(cacheDict: dict):
    cacheDictCopy = cacheDict.copy()
    for cacheID, cacheData in cacheDictCopy.items():
        cacheItemAge = datetime.now().timestamp() - cacheData.timestampLastUsed
        if cacheItemAge > MAX_CACHE_AGE_SECONDS:
            logging.info("Deleting cache item " + str(cacheID) + " as it was last used before: " + str(cacheItemAge) + " seconds")
            del cacheDict[cacheID]


def getUserFromDB(userDB: Database, userID: Union[str, int], addIfNew: bool, updateUsageTimestamp: bool) -> Union[User, None]:
    """ Returns user from given DB. Adds it to DB if wished and it doesn't exist. """
    user = User.load(userDB, str(userID))
    if user is not None:
        # Store a rough timestamp of when user used bot last time
        if updateUsageTimestamp and user.updateActivityTimestamp():
            user.store(userDB)
    elif addIfNew:
        """ New user? --> Add userID to DB if wished. """
        # Add user to DB for the first time
        logging.info(f'Storing new userID: {userID}')
        user = User(id=str(userID))
        user.store(userDB)

    return user


class BKBot:
    my_parser = argparse.ArgumentParser()
    my_parser.add_argument('-fc', '--forcechannelupdatewithresend',
                           help='Sofortiges Channelupdates mit löschen- und neu Einsenden aller Coupons.', type=bool,
                           default=False)
    my_parser.add_argument('-rc', '--resumechannelupdate',
                           help='Channelupdate fortsetzen: Coupons ergänzen, die nicht rausgeschickt wurden und Couponübersicht erneuern. Nützlich um ein Channelupdate bei einem Abbruch genau an derselben Stelle fortzusetzen.',
                           type=bool,
                           default=False)
    my_parser.add_argument('-fb', '--forcebatchprocess',
                           help='Alle Aktionen ausführen, die eigentlich nur täglich 1x durchlaufen: Crawler, User Benachrichtigungen rausschicken und Channelupdate mit Löschen- und neu Einsenden.',
                           type=bool, default=False)
    my_parser.add_argument('-un', '--usernotify',
                           help='User beim Start sofort benachrichtigen über abgelaufene favorisierte Coupons, die wieder zurück sind und neue Coupons (= Coupons, die seit dem letzten DB Update neu hinzu kamen).',
                           type=bool, default=False)
    my_parser.add_argument('-n', '--nukechannel', help='Alle Nachrichten im Channel automatisiert löschen (debug/dev Funktion)', type=bool, default=False)
    my_parser.add_argument('-cc', '--cleanupchannel', help='Zu löschende alte Coupon-Posts aus dem Channel löschen.', type=bool, default=False)
    my_parser.add_argument('-m', '--migrate', help='DB Migrationen ausführen falls verfügbar', type=bool, default=False)
    my_parser.add_argument('-c', '--crawl', help='Crawler beim Start des Bots einmalig ausführen.', type=bool, default=False)
    my_parser.add_argument('-mm', '--maintenancemode', help='Wartungsmodus - zeigt im Bot und Channel eine entsprechende Meldung. Deaktiviert alle Bot Funktionen.', type=bool,
                           default=False)
    args = my_parser.parse_args()

    def __init__(self):
        self.couponImageCache: dict = {}
        self.couponImageQRCache: dict = {}
        self.offerImageCache: dict = {}
        self.maintenanceMode = self.args.maintenancemode
        self.cfg = loadConfig()
        if self.cfg is None:
            raise Exception('Broken or missing config')
        self.crawler = BKCrawler()
        self.crawler.setExportCSVs(False)
        self.crawler.setKeepHistoryDB(False)
        self.crawler.setKeepSimpleHistoryDB(False)
        self.crawler.setStoreCouponAPIDataAsJson(False)
        self.publicChannelName = self.cfg.public_channel_name
        self.botName = self.cfg.bot_name
        self.couchdb = self.crawler.couchdb
        self.application = Application.builder().token(self.cfg.bot_token).read_timeout(30).write_timeout(30).build()
        self.initHandlers()
        self.application.add_error_handler(self.botErrorCallback)
        # self.lock = asyncio.Lock()
        self.statsCached: Union[UserStats, None] = None
        self.statsCachedTimestamp: float = -1

    def initHandlers(self):
        """ Adds all handlers to dispatcher (not error_handlers!!) """
        # Main conversation handler - handles nearly all bot menus.
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('start', self.botDisplayMenuMain), CommandHandler('favoriten', self.botDisplayFavoritesCOMMAND),
                          CommandHandler('coupons', self.botDisplayAllCouponsCOMMAND), CommandHandler('coupons2', self.botDisplayAllCouponsWithoutMenuCOMMAND),
                          CommandHandler('angebote', self.botDisplayOffers), CommandHandler('payback', self.botDisplayPaybackCard),
                          CommandHandler('einstellungen', self.botDisplayMenuSettings),
                          CommandHandler(Commands.MAINTENANCE, self.botAdminToggleMaintenanceMode),
                          CallbackQueryHandler(self.botDisplayMenuMain, pattern='^' + CallbackVars.MENU_MAIN + '$')],
            states={
                CallbackVars.MENU_MAIN: [
                    # Main menu
                    # CallbackQueryHandler(self.botDisplayMenuMain, pattern='^' + CallbackVars.MENU_MAIN + '$'),  # E.g. "back" button on error -> Go back to main menu
                    CallbackQueryHandler(self.botDisplayAllCouponsListWithFullTitles, pattern='^' + CallbackVars.MENU_DISPLAY_ALL_COUPONS_LIST_WITH_FULL_TITLES + '$'),
                    CallbackQueryHandler(self.botDisplayCouponsFromBotMenu, pattern=CallbackPattern.DISPLAY_COUPONS),
                    CallbackQueryHandler(self.botDisplayCouponsWithImagesFavorites, pattern='^' + CallbackVars.MENU_COUPONS_FAVORITES_WITH_IMAGES + '$'),
                    CallbackQueryHandler(self.botDisplayOffers, pattern='^' + CallbackVars.MENU_OFFERS + '$'),
                    CallbackQueryHandler(self.botDisplayFeedbackCodes, pattern='^' + CallbackVars.MENU_FEEDBACK_CODES + '$'),
                    CallbackQueryHandler(self.botAddPaybackCard, pattern="^" + CallbackVars.MENU_SETTINGS_ADD_PAYBACK_CARD + "$"),
                    CallbackQueryHandler(self.botDisplayPaybackCard, pattern='^' + CallbackVars.MENU_DISPLAY_PAYBACK_CARD + '$'),
                    CallbackQueryHandler(self.botDisplayMenuSettings, pattern='^' + CallbackVars.MENU_SETTINGS + '$')
                ],
                CallbackVars.MENU_OFFERS: [
                    CallbackQueryHandler(self.botDisplayCouponsFromBotMenu, pattern=CallbackPattern.DISPLAY_COUPONS),
                    # Back to main menu
                    CallbackQueryHandler(self.botDisplayMenuMain, pattern='^' + CallbackVars.MENU_MAIN + '$'),
                ],
                CallbackVars.MENU_FEEDBACK_CODES: [
                    # Back to main menu
                    CallbackQueryHandler(self.botDisplayMenuMain, pattern='^' + CallbackVars.MENU_MAIN + '$'),
                ],
                CallbackVars.MENU_DISPLAY_COUPON: [
                    # Back to last coupons menu
                    CallbackQueryHandler(self.botDisplayCouponsFromBotMenu, pattern=CallbackPattern.DISPLAY_COUPONS),
                    # Display single coupon
                    CallbackQueryHandler(self.botDisplaySingleCoupon, pattern='.*a=dc.*'),
                    # Back to main menu
                    CallbackQueryHandler(self.botDisplayMenuMain, pattern='^' + CallbackVars.MENU_MAIN + '$'),
                    CallbackQueryHandler(self.botDisplayEasterEgg, pattern='^' + CallbackVars.EASTER_EGG + '$'),
                ],
                CallbackVars.MENU_DISPLAY_PAYBACK_CARD: [
                    # Back to last coupons menu
                    CallbackQueryHandler(self.botDisplayMenuMain, pattern='^' + CallbackVars.GENERIC_BACK + '$'),
                    CallbackQueryHandler(self.botAddPaybackCard, pattern="^" + CallbackVars.MENU_SETTINGS_ADD_PAYBACK_CARD + "$"),
                    CallbackQueryHandler(self.botDeletePaybackCard, pattern="^" + CallbackVars.MENU_SETTINGS_DELETE_PAYBACK_CARD + "$")
                ],
                CallbackVars.MENU_SETTINGS: [
                    # Back to main menu
                    CallbackQueryHandler(self.botDisplayMenuMain, pattern='^' + CallbackVars.MENU_MAIN + '$'),
                    CallbackQueryHandler(self.botDisplaySettingsToggleSetting, pattern=generateCallbackRegEx(User().settings)),
                    CallbackQueryHandler(self.botResetSortSettings, pattern="^" + CallbackVars.MENU_SETTINGS_SORTS_RESET + "$"),
                    CallbackQueryHandler(self.botResetSettings, pattern="^" + CallbackVars.MENU_SETTINGS_RESET + "$"),
                    CallbackQueryHandler(self.botDeleteUnavailableFavoriteCoupons, pattern="^" + CallbackVars.MENU_SETTINGS_DELETE_UNAVAILABLE_FAVORITE_COUPONS + "$"),
                    CallbackQueryHandler(self.botAddPaybackCard, pattern="^" + CallbackVars.MENU_SETTINGS_ADD_PAYBACK_CARD + "$"),
                    CallbackQueryHandler(self.botDeletePaybackCard, pattern="^" + CallbackVars.MENU_SETTINGS_DELETE_PAYBACK_CARD + "$"),
                    CallbackQueryHandler(self.botDisplayEasterEgg, pattern='^' + CallbackVars.EASTER_EGG + '$'),
                ],
                CallbackVars.MENU_SETTINGS_ADD_PAYBACK_CARD: [
                    # Back to settings menu
                    CallbackQueryHandler(self.botDisplayMenuSettings, pattern='^' + CallbackVars.GENERIC_BACK + '$'),
                    MessageHandler(filters=filters.TEXT and (~filters.COMMAND), callback=self.botAddPaybackCard),
                ],
                CallbackVars.MENU_SETTINGS_DELETE_PAYBACK_CARD: [
                    # Back to settings menu
                    CallbackQueryHandler(self.botDisplayMenuSettings, pattern='^' + CallbackVars.GENERIC_BACK + '$'),
                    MessageHandler(filters.TEXT, self.botDeletePaybackCard),
                ],
            },
            fallbacks=[CommandHandler('start', self.botDisplayMenuMain)],
            name="MainConversationHandler",
            allow_reentry=True
        )
        """ Handles deletion of user accounts. """
        conv_handler2 = ConversationHandler(
            entry_points=[CommandHandler(Commands.DELETE_ACCOUNT, self.botUserDeleteAccountSTART_COMMAND),
                          CallbackQueryHandler(self.botUserDeleteAccountSTART_MENU, pattern="^" + CallbackVars.MENU_SETTINGS_USER_DELETE_ACCOUNT + "$")],
            states={
                CallbackVars.MENU_SETTINGS_USER_DELETE_ACCOUNT: [
                    # Back to settings menu
                    CallbackQueryHandler(self.botDisplayMenuSettings, pattern='^' + CallbackVars.GENERIC_BACK + '$'),
                    # Back to main menu
                    CallbackQueryHandler(self.botDisplayMenuMain, pattern='^' + CallbackVars.MENU_MAIN + '$'),
                    # Delete users account
                    MessageHandler(filters=filters.TEXT and (~filters.COMMAND), callback=self.botUserDeleteAccount),
                ],

            },
            fallbacks=[CommandHandler('start', self.botDisplayMenuMain)],
            name="DeleteUserConvHandler",
            allow_reentry=True
        )
        """ Handles 'favorite buttons' below single coupon images. """
        conv_handler3 = ConversationHandler(
            entry_points=[CallbackQueryHandler(self.botCouponToggleFavorite, pattern=PATTERN.PLU_TOGGLE_FAV)],
            states={
                CallbackVars.COUPON_LOOSE_WITH_FAVORITE_SETTING: [
                    CallbackQueryHandler(self.botCouponToggleFavorite, pattern=PATTERN.PLU_TOGGLE_FAV),
                ],

            },
            fallbacks=[CommandHandler('start', self.botDisplayMenuMain)],
            name="CouponToggleFavoriteWithImageHandler",
        )
        app = self.application
        app.add_handler(conv_handler)
        app.add_handler(conv_handler2)
        app.add_handler(conv_handler3)
        app.add_handler(CommandHandler('stats', self.botDisplayStats))

    def adminOrException(self, user: User):
        if not self.isAdmin(user):
            raise BetterBotException(SYMBOLS.DENY + ' <b>Dir fehlen die Rechte zum Ausführen dieser Aktion!</b>')

    def isAdmin(self, user: User) -> bool:
        if user is not None and self.cfg.admin_ids is not None and user.id in self.cfg.admin_ids:
            return True
        else:
            return False

    async def botErrorCallback(self, update: Update, context: CallbackContext):
        try:
            raise context.error
        except BetterBotException as botError:
            errorText = botError.getErrorMsg()
            try:
                await self.sendMessage(chat_id=update.effective_user.id, text=errorText, reply_markup=botError.getReplyMarkup(), parse_mode="HTML")
            except:
                logging.warning('Exception during exception handling -> Raising initial Exception')
                raise botError

    async def handleBotErrorGently(self, update: Update, context: CallbackContext, botError: BetterBotException):
        """ Can handle BetterBotExceptions -> Answers user with the previously hopefully meaningful messages defined in BetterBotException.getErrorMsg(). """
        await self.editOrSendMessage(update, text=botError.getErrorMsg(), parse_mode="HTML", reply_markup=botError.getReplyMarkup())

    def getPublicChannelName(self, fallback=None) -> Union[str, None]:
        """ Returns name of public channel which this bot is taking care of. """
        if self.publicChannelName is not None:
            return self.publicChannelName
        else:
            return fallback

    def getPublicChannelChatID(self) -> Union[str, None]:
        """ Returns public channel chatID like "@ChannelName". """
        if self.getPublicChannelName() is None:
            return None
        else:
            return '@' + self.getPublicChannelName()

    def getPublicChannelHyperlinkWithCustomizedText(self, linkText: str) -> str:
        """ Returns: e.g. <a href="https://t.me/channelName">linkText</a>
        Only call this if self.publicChannelName != None!!! """
        return "<a href=\"https://t.me/" + self.getPublicChannelName() + "\">" + linkText + "</a>"

    def getPublicChannelFAQLink(self) -> Union[str, None]:
        if self.publicChannelName is None:
            return None
        else:
            return f"https://t.me/{self.publicChannelName}/{self.cfg.public_channel_post_id_faq}"

    async def botDisplayMaintenanceMode(self, update: Update, context: CallbackContext):
        text = SYMBOLS.DENY + '<b>Wartungsmodus!' + SYMBOLS.DENY + '</b>'
        text += '\nKeine Sorge solange der Bot reagiert, lebt er auch noch ;)'
        if self.getPublicChannelName() is not None:
            text += '\nMehr Infos siehe ' + self.getPublicChannelHyperlinkWithCustomizedText('Channel') + '.'
        user = self.getUser(userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        if self.isAdmin(user):
            text += '\nWartungsmodus deaktivieren: /' + Commands.MAINTENANCE
        await self.editOrSendMessage(update, text=text, parse_mode='HTML', disable_web_page_preview=True)

    async def botDisplayMenuMain(self, update: Update, context: CallbackContext):
        user = self.getUser(userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        allButtons = []
        if self.getPublicChannelName() is not None:
            allButtons.append([InlineKeyboardButton('Alle Coupons Liste + Pics + News', url='https://t.me/' + self.getPublicChannelName())])
            if user.settings.displayCouponCategoryAllCouponsLongListWithLongTitles:
                allButtons.append([InlineKeyboardButton('Alle Coupons Liste lange Titel + Pics', callback_data=CallbackVars.MENU_DISPLAY_ALL_COUPONS_LIST_WITH_FULL_TITLES)])
        allButtons.append([InlineKeyboardButton('Alle Coupons', callback_data=CouponCallbackVars.ALL_COUPONS)])
        allButtons.append([InlineKeyboardButton('Coupons ohne Menü', callback_data=CouponCallbackVars.ALL_COUPONS_WITHOUT_MENU)])
        for couponSrc in BotAllowedCouponTypes:
            # Only add buttons for coupon categories for which at least one coupon is available
            couponCategory = self.crawler.getCachedCouponCategory(couponSrc)
            if couponCategory is None:
                continue
            elif couponSrc == CouponType.PAYBACK and not user.settings.displayCouponCategoryPayback:
                # Do not display this category if disabled by user
                continue
            allButtons.append([InlineKeyboardButton(CouponCategory(couponSrc).namePlural, callback_data=f"?a=dcs&m={CouponViews.CATEGORY.getViewCode()}&cs={couponSrc}")])
            if couponCategory.numberofCouponsWithFriesAndDrink < couponCategory.numberofCouponsTotal and couponCategory.isEatable():
                allButtons.append([InlineKeyboardButton(CouponCategory(couponSrc).namePlural + ' ohne Menü',
                                                        callback_data=f"?a=dcs&m={CouponViews.CATEGORY_WITHOUT_MENU.getViewCode()}&cs={couponSrc}")])
            if couponSrc == CouponType.APP and couponCategory.numberofCouponsHidden > 0 and user.settings.displayCouponCategoryAppCouponsHidden:
                allButtons.append([InlineKeyboardButton(CouponCategory(couponSrc).namePlural + ' versteckte',
                                                        callback_data=f"?a=dcs&m={CouponViews.HIDDEN_APP_COUPONS_ONLY.getViewCode()}&cs={couponSrc}")])
        # if user.settings.displayCouponCategoryAllExceptPlantBased:
        #     allButtons.append([InlineKeyboardButton(f'{SYMBOLS.MEAT}Coupons ohne PlantBased{SYMBOLS.MEAT}', callback_data=CouponCallbackVars.MEAT_WITHOUT_PLANT_BASED)])
        if user.settings.displayCouponCategoryVeggie:
            allButtons.append([InlineKeyboardButton(f'{SYMBOLS.BROCCOLI}Veggie Coupons{SYMBOLS.BROCCOLI}', callback_data=CouponCallbackVars.VEGGIE)])
        keyboardCouponsFavorites = [InlineKeyboardButton(SYMBOLS.STAR + 'Favoriten' + SYMBOLS.STAR, callback_data=f"?a=dcs&m={CouponViews.FAVORITES.getViewCode()}"),
                                    InlineKeyboardButton(SYMBOLS.STAR + 'Favoriten + Pics' + SYMBOLS.STAR, callback_data=CallbackVars.MENU_COUPONS_FAVORITES_WITH_IMAGES)]
        allButtons.append(keyboardCouponsFavorites)
        if user.settings.displayCouponCategoryPayback:
            if user.getPaybackCardNumber() is None:
                allButtons.append([InlineKeyboardButton(SYMBOLS.CIRLCE_BLUE + 'Payback Karte hinzufügen', callback_data=CallbackVars.MENU_SETTINGS_ADD_PAYBACK_CARD)])
            else:
                allButtons.append([InlineKeyboardButton(SYMBOLS.PARK + 'ayback Karte', callback_data=CallbackVars.MENU_DISPLAY_PAYBACK_CARD)])
        alwaysShowOfferButton = True  # 2022-09-28: Always show offer button because BK website may have some offers
        if user.settings.displayOffersButton and (self.crawler.cachedNumberofAvailableOffers > 0 or alwaysShowOfferButton):
            allButtons.append(
                [InlineKeyboardButton('Angebote', callback_data=CallbackVars.MENU_OFFERS)])
        if user.settings.displayBKWebsiteURLs:
            allButtons.append(
                [InlineKeyboardButton('Spar Kings', url=URLs.BK_SPAR_KINGS), InlineKeyboardButton('KING Finder', url=URLs.PROTOCOL_BK + URLs.BK_KING_FINDER)])
        if user.settings.displayFeedbackCodeGenerator:
            allButtons.append([InlineKeyboardButton('Feedback Code Generator', callback_data=CallbackVars.MENU_FEEDBACK_CODES)])
        if self.publicChannelName is not None and user.settings.displayFAQLinkButton:
            allButtons.append([InlineKeyboardButton('FAQ', url=self.getPublicChannelFAQLink())])
        allButtons.append([InlineKeyboardButton(SYMBOLS.WRENCH + 'Einstellungen', callback_data=CallbackVars.MENU_SETTINGS)])
        reply_markup = InlineKeyboardMarkup(allButtons)
        menuText = 'Hallo ' + update.effective_user.first_name + ', <b>Bock auf Fastfood?</b>'
        menuText += '\n' + getBotImpressum()
        missingPaperCouponsText = self.crawler.getMissingPaperCouponsText()
        if missingPaperCouponsText is not None:
            menuText += '\n<b>'
            menuText += SYMBOLS.WARNING + 'Derzeit im Bot fehlende Papiercoupons: ' + missingPaperCouponsText
            if self.publicChannelName is not None:
                menuText += f"\nVollständige Papiercouponbögen sind im FAQ  <a href=\"{self.getPublicChannelFAQLink()}\">FAQ</a> verlinkt."
            menuText += '</b>'
        if self.isAdmin(user):
            menuText += '\n<b>Du bist Admin!</b>'
            menuText += '\nAdmin Commands:'
            menuText += '\n/' + Commands.MAINTENANCE + ' - Wartungsmodus toggeln'
        query = update.callback_query
        if query is not None:
            await query.answer()
        await self.editOrSendMessage(update, text=menuText, reply_markup=reply_markup, parse_mode='HTML', disable_web_page_preview=True)
        return CallbackVars.MENU_MAIN

    async def botDisplayAllCouponsListWithFullTitles(self, update: Update, context: CallbackContext):
        """ Send list containing all coupons with long titles linked to coupon channel to user. This may result in up to 10 messages being sent! """
        query = update.callback_query
        if query is not None:
            await update.callback_query.answer()
        activeCoupons = self.getFilteredCouponsAsDict(CouponFilter(), True)
        await self.sendCouponOverviewWithChannelLinks(chat_id=update.effective_user.id, coupons=activeCoupons, useLongCouponTitles=True,
                                                      channelDB=self.couchdb[DATABASES.TELEGRAM_CHANNEL], infoDB=None, infoDBDoc=None)
        # Delete last message containing menu as it is of no use for us anymore
        await self.deleteMessage(chat_id=update.effective_user.id, messageID=update.callback_query.message.message_id)
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN)]])
        menuText = "<b>Alle " + str(len(activeCoupons)) + " Coupons als Liste mit langen Titeln</b>"
        if self.getPublicChannelName() is not None:
            menuText += "\nAlle Verlinkungen führen in den " + self.getPublicChannelHyperlinkWithCustomizedText("Channel") + "."
        await self.sendMessage(chat_id=update.effective_user.id, text=menuText, parse_mode="HTML", reply_markup=reply_markup, disable_web_page_preview=True)
        return CallbackVars.MENU_MAIN

    async def botDisplayCouponsFromBotMenu(self, update: Update, context: CallbackContext):
        """ Wrapper """
        await self.displayCoupons(update, context, update.callback_query.data)
        return CallbackVars.MENU_DISPLAY_COUPON

    async def botDisplayAllCouponsCOMMAND(self, update: Update, context: CallbackContext):
        """ Wrapper and this is only to be used for commands. """
        await self.displayCoupons(update, context, CouponCallbackVars.ALL_COUPONS)
        return CallbackVars.MENU_DISPLAY_COUPON

    async def botDisplayAllCouponsWithoutMenuCOMMAND(self, update: Update, context: CallbackContext):
        """ Wrapper and this is only to be used for commands. """
        await self.displayCoupons(update, context, CouponCallbackVars.ALL_COUPONS_WITHOUT_MENU)
        return CallbackVars.MENU_DISPLAY_COUPON

    async def botDisplayFavoritesCOMMAND(self, update: Update, context: CallbackContext):
        """ Wrapper and this is only to be used for commands. """
        await self.displayCoupons(update, context, CouponCallbackVars.FAVORITES)
        return CallbackVars.MENU_DISPLAY_COUPON

    async def botDisplayStats(self, update: Update, context: CallbackContext):
        query = update.callback_query
        if query is not None:
            await query.answer()
        userDB = self.crawler.getUserDB()
        loadingMessage = None
        currentDatetime = getCurrentDate()
        if self.statsCached is None or currentDatetime.timestamp() - self.statsCachedTimestamp > 30 * 60:
            # Init/Refresh cache
            loadingMessage = await asyncio.create_task(self.editOrSendMessage(update, text='Statistiken werden geladen...'))
            self.statsCached = UserStats(userDB)
            self.statsCachedTimestamp = currentDatetime.timestamp()
        couponDB = self.getFilteredCouponsAsList(couponFilter=CouponFilter())
        userStats = self.statsCached
        user = getUserFromDB(userDB=userDB, userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        text = '<b>Hallo <s>Nerd</s> ' + update.effective_user.first_name + '</b>'
        text += '\n<pre>'
        text += 'Anzahl User im Bot: ' + str(len(userDB))
        text += '\nAnzahl von Usern gesetzte Favoriten: ' + str(userStats.numberofFavorites)
        text += '\nAnzahl User, die das Easter-Egg entdeckt haben: ' + str(userStats.numberofUsersWhoFoundEasterEgg)
        text += '\nAnzahl User, die den Bot wahrscheinlich geblockt haben: ' + str(userStats.numberofUsersWhoProbablyBlockedBot)
        text += f'\nAnzahl User, die den Bot innerhalb der letzten {MAX_HOURS_ACTIVITY_TRACKING}h genutzt haben: ' + str(userStats.numberofUsersWhoRecentlyUsedBot)
        text += '\nAnzahl User, die eine PB Karte hinzugefügt haben: ' + str(userStats.numberofUsersWhoAddedPaybackCard)
        text += '\nAnzahl gültige Bot Coupons: ' + str(len(couponDB))
        text += '\nAnzahl gültige Angebote: ' + str(len(self.crawler.getOffersActive()))
        text += f'\nStatistiken generiert am: {formatDateGerman(self.statsCachedTimestamp)}'
        text += '\n---'
        text += '\nDein BetterKing Account:'
        text += '\nAnzahl Aufrufe Easter-Egg: ' + str(user.easterEggCounter)
        text += '\nAnzahl gesetzte Favoriten (inkl. abgelaufenen): ' + str(len(user.favoriteCoupons))
        text += f'\nBot  zuletzt verwendet (auf {MAX_HOURS_ACTIVITY_TRACKING}h genau, Zeitpunkt von vom Bot zugestelltem Coupon-Benachrichtigungen zählen auch als Aktivität): ' + formatDateGerman(
            user.timestampLastTimeAccountUsed)
        text += '</pre>'
        if loadingMessage is not None:
            await self.editMessage(chat_id=loadingMessage.chat_id, message_id=loadingMessage.message_id, text=text, parse_mode='html', disable_web_page_preview=True)
        else:
            await self.sendMessage(chat_id=update.effective_user.id, text=text, parse_mode='html', disable_web_page_preview=True)
        return ConversationHandler.END

    async def displayCoupons(self, update: Update, context: CallbackContext, callbackVar: str):
        """ Displays all coupons in a pre selected mode """
        # Important! This is required so that we can e.g. jump from "Category 'App coupons' page 2 display single coupon" back into "Category 'App coupons' page 2"
        callbackVar += "&cb=" + urllib.parse.quote(callbackVar)
        urlquery = furl(callbackVar)
        urlinfo = urlquery.args
        view = getCouponViewByIndex(index=int(urlinfo["m"]))
        action = urlinfo.get('a')
        try:
            saveUserToDB = False
            userDB = self.crawler.getUserDB()
            user = getUserFromDB(userDB=userDB, userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=False)
            if user.updateActivityTimestamp():
                saveUserToDB = True
            if view.allowModifyFilter:
                # Inherit some filters from user settings
                view = deepcopy(view)
                couponFilter = view.getFilter()
                couponTypeStr = urlinfo['cs']
                if couponTypeStr is not None and len(couponTypeStr) > 0:
                    couponFilter.allowedCouponTypes = [int(couponTypeStr)]
                # First we only want to filter coupons. Sort them later according to user preference -> Needs less CPU cycles.
                if couponFilter.isHidden is None and user.settings.displayHiddenAppCouponsWithinGenericCategories is False:
                    # User does not want to see hidden coupons within generic categories
                    couponFilter.isHidden = False
                if couponFilter.isPlantBased is None and user.settings.displayPlantBasedCouponsWithinGenericCategories is False:
                    # User does not want to see plant based coupons within generic categories
                    couponFilter.isPlantBased = False
                if view.highlightFavorites is None:
                    # User setting overrides unser param in view
                    view.highlightFavorites = user.settings.highlightFavoriteCouponsInButtonTexts
            if view == CouponViews.FAVORITES:
                userFavorites, menuText = self.getUserFavoritesAndUserSpecificMenuText(user=user, sortCoupons=False)
                coupons = userFavorites.couponsAvailable
                couponCategory = CouponCategory(coupons)
            else:
                coupons = self.getFilteredCouponsAsList(view.getFilter(), sortIfSortCodeIsGivenInCouponFilter=False)
                couponCategory = CouponCategory(coupons, title=view.title)
                menuText = couponCategory.getCategoryInfoText()
            if len(coupons) == 0:
                # This should never happen
                raise BetterBotException(SYMBOLS.DENY + ' <b>Ausnahmefehler: Es gibt derzeit keine Coupons!</b>',
                                         InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=urlquery.url)]]))
            if action == 'dcss':
                # Change sort of coupons
                saveUserToDB = True
                nextSortMode = user.getNextSortModeForCouponView(couponView=view)
                # Sort coupons
                coupons = sortCouponsAsList(coupons, nextSortMode)
                user.setCustomSortModeForCouponView(couponView=view, sortMode=nextSortMode)
            else:
                # Sort coupons
                coupons = sortCouponsAsList(coupons, user.getSortModeForCouponView(couponView=view))
            # Answer query
            query = update.callback_query
            if query is not None:
                await query.answer()
            # Build bot menu
            urlquery_callbackBack = furl(urlquery.args["cb"])
            buttons = []
            maxCouponsPerPage = 20
            paginationMax = math.ceil(len(coupons) / maxCouponsPerPage)
            desiredPage = int(urlquery.args.get("p", 1))
            if desiredPage > paginationMax:
                # Fallback - can happen if user leaves menu open for a long time, DB changes, user presses "next/previous page" button but max page number has changed in the meanwhile.
                currentPage = paginationMax
            else:
                currentPage = desiredPage
            # Grab all items in desired range (= on desired page)
            index = (currentPage * maxCouponsPerPage - maxCouponsPerPage)
            # Whenever the user has at least one favorite coupon on page > 1 we'll replace the dummy button in the middle and add Easter Egg functionality :)
            currentPageContainsAtLeastOneFavoriteCoupon = False
            includeVeggieSymbol = user.settings.highlightVeggieCouponsInCouponButtonTexts
            if view.includeVeggieSymbol is not None:
                # Override user setting
                includeVeggieSymbol = view.includeVeggieSymbol
            while len(buttons) < maxCouponsPerPage and index < len(coupons):
                coupon = coupons[index]
                if user.isFavoriteCoupon(coupon) and view.highlightFavorites:
                    buttonText = SYMBOLS.STAR + coupon.generateCouponShortText(highlightIfNew=user.settings.highlightNewCouponsInCouponButtonTexts,
                                                                               includeVeggieSymbol=includeVeggieSymbol)
                    currentPageContainsAtLeastOneFavoriteCoupon = True
                else:
                    buttonText = coupon.generateCouponShortText(highlightIfNew=user.settings.highlightNewCouponsInCouponButtonTexts, includeVeggieSymbol=includeVeggieSymbol)
                buttons.append([InlineKeyboardButton(buttonText, callback_data="?a=dc&plu=" + coupon.id + "&cb=" + urllib.parse.quote(urlquery_callbackBack.url))])
                index += 1
            numberofCouponsOnCurrentPage = len(buttons)
            if paginationMax > 1:
                # Add pagination navigation buttons if needed
                menuText += "\nSeite " + str(currentPage) + "/" + str(paginationMax)
                navigationButtons = []
                urlquery_callbackBack.args['a'] = 'dcs'
                if currentPage > 1:
                    # Add button to go to previous page
                    previousPage = currentPage - 1
                    urlquery_callbackBack.args['p'] = previousPage
                    navigationButtons.append(InlineKeyboardButton(SYMBOLS.ARROW_LEFT, callback_data=urlquery_callbackBack.url))
                else:
                    # Add dummy button for a consistent button layout
                    navigationButtons.append(InlineKeyboardButton(SYMBOLS.GHOST, callback_data="DummyButtonPrevPage"))
                navigationButtons.append(InlineKeyboardButton("Seite " + str(currentPage) + "/" + str(paginationMax), callback_data="DummyButtonMiddle"))
                if currentPage < paginationMax:
                    # Add button to go to next page
                    nextPage = currentPage + 1
                    urlquery_callbackBack.args['p'] = nextPage
                    navigationButtons.append(InlineKeyboardButton(SYMBOLS.ARROW_RIGHT, callback_data=urlquery_callbackBack.url))
                else:
                    # Add dummy button for a consistent button layout
                    # Easter egg: Trigger it if there are at least two pages available AND user is currently on the last page AND that page contains at least one user-favorited coupon.
                    if currentPageContainsAtLeastOneFavoriteCoupon and currentPage > 1:
                        navigationButtons.append(InlineKeyboardButton(SYMBOLS.GHOST, callback_data=CallbackVars.EASTER_EGG))
                    else:
                        navigationButtons.append(InlineKeyboardButton(SYMBOLS.GHOST, callback_data="DummyButtonNextPage"))
                buttons.append(navigationButtons)
            # Display sort button if it makes sense
            possibleSortModes = couponCategory.getSortModes()
            if user.settings.displayCouponSortButton and len(possibleSortModes) > 1 and numberofCouponsOnCurrentPage > 1:
                currentSortMode = user.getSortModeForCouponView(couponView=view)
                nextSortMode = user.getNextSortModeForCouponView(couponView=view)
                urlquery_callbackBack.args['a'] = 'dcss'
                urlquery_callbackBack.args['p'] = currentPage
                buttons.append(
                    [InlineKeyboardButton(currentSortMode.text + ' | 🔃 | ' + nextSortMode.text, callback_data=urlquery_callbackBack.url)])

            buttons.append([InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN)])
            reply_markup = InlineKeyboardMarkup(buttons)
            await self.editOrSendMessage(update, text=menuText, reply_markup=reply_markup, parse_mode='HTML')
            if saveUserToDB:
                # User document has changed -> Update DB
                user.store(db=userDB)
        except BetterBotException as botError:
            await self.handleBotErrorGently(update, context, botError)

    def getUserFavoritesAndUserSpecificMenuText(self, user: User, coupons: Union[dict, None] = None, sortCoupons: bool = False) -> Tuple[UserFavoritesInfo, str]:
        if len(user.favoriteCoupons) == 0:
            raise BetterBotException('<b>Du hast noch keine Favoriten!</b>', InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN)]]))
        if coupons is None:
            # Perform DB request if not already done before
            coupons = self.crawler.getFilteredCouponsAsDict(filter=CouponViews.FAVORITES.getFilter())
        userFavoritesInfo = user.getUserFavoritesInfo(couponsFromDB=coupons, sortCoupons=sortCoupons)
        if len(userFavoritesInfo.couponsAvailable) == 0:
            errorMessage = '<b>' + SYMBOLS.WARNING + 'Derzeit ist keiner deiner ' + str(len(user.favoriteCoupons)) + ' Favoriten verfügbar:</b>'
            errorMessage += '\n' + userFavoritesInfo.getUnavailableFavoritesText()
            if user.isAllowSendFavoritesNotification():
                errorMessage += '\n' + SYMBOLS.CONFIRM + 'Du wirst benachrichtigt, sobald abgelaufene Favoriten wieder verfügbar sind.'
            raise BetterBotException(errorMessage, InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN)]]))

        menuText = SYMBOLS.STAR
        if len(userFavoritesInfo.couponsUnavailable) == 0:
            menuText += str(len(userFavoritesInfo.couponsAvailable)) + ' Favoriten verfügbar' + SYMBOLS.STAR
        else:
            menuText += str(len(userFavoritesInfo.couponsAvailable)) + '/' + str(len(user.favoriteCoupons)) + ' Favoriten verfügbar' + SYMBOLS.STAR
        couponCategoryDummy = CouponCategory(coupons=userFavoritesInfo.couponsAvailable)
        menuText += '\n' + couponCategoryDummy.getExpireDateInfoText()
        priceInfo = couponCategoryDummy.getPriceInfoText()
        if priceInfo is not None:
            menuText += "\n" + priceInfo

        if len(userFavoritesInfo.couponsUnavailable) > 0:
            menuText += '\n' + SYMBOLS.WARNING + str(len(userFavoritesInfo.couponsUnavailable)) + ' deiner Favoriten sind abgelaufen:'
            menuText += '\n' + userFavoritesInfo.getUnavailableFavoritesText()
            menuText += '\n' + SYMBOLS.INFORMATION + 'In den Einstellungen kannst du abgelaufene Favoriten löschen oder dich benachrichtigen lassen, sobald diese wieder verfügbar sind.'
        return userFavoritesInfo, menuText

    async def botDisplayEasterEgg(self, update: Update, context: CallbackContext):
        query = update.callback_query
        if query is not None:
            await query.answer()
        userDB = self.crawler.getUserDB()
        user = getUserFromDB(userDB=userDB, userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        user.easterEggCounter += 1
        user.store(db=userDB)
        logging.info(f"User {user.id} found easter egg times {user.easterEggCounter}")
        text = "🥚<b>Glückwunsch! Du hast das Easter Egg gefunden!</b>"
        text += "\nKlicke <a href=\"https://www.youtube.com/watch?v=dQw4w9WgXcQ\">HIER</a>, um es anzusehen ;)"
        text += "\nDrücke /start, um das Menü neu zu laden."
        await self.sendMessage(chat_id=update.effective_user.id, text=text, parse_mode="html", disable_web_page_preview=True)
        return CallbackVars.MENU_DISPLAY_COUPON

    async def botDisplayCouponsWithImagesFavorites(self, update: Update, context: CallbackContext):
        query = update.callback_query
        if query is not None:
            await query.answer()
        try:
            userFavorites, favoritesInfoText = self.getUserFavoritesAndUserSpecificMenuText(
                user=self.getUser(userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True), sortCoupons=True)
        except BetterBotException as botError:
            await self.handleBotErrorGently(update, context, botError)
            return CallbackVars.MENU_DISPLAY_COUPON
        await self.displayCouponsWithImagesAndBackButton(update, context, userFavorites.couponsAvailable, topMsgText='<b>Alle Favoriten mit Bildern:</b>',
                                                         bottomMsgText=favoritesInfoText)
        if query is not None:
            # Delete last message containing bot menu
            await context.bot.delete_message(chat_id=update.effective_message.chat_id, message_id=query.message.message_id)
        return CallbackVars.MENU_DISPLAY_COUPON

    async def displayCouponsWithImagesAndBackButton(self, update: Update, context: CallbackContext, coupons: list, topMsgText: str, bottomMsgText: str = "Zurück zum Hauptmenü?"):
        await self.displayCouponsWithImages(update, context, coupons, topMsgText)
        # Post back button
        await update.effective_message.reply_text(text=bottomMsgText, parse_mode="HTML",
                                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN)], []]))

    async def displayCouponsWithImages(self, update: Update, context: CallbackContext, coupons: list, msgText: str):
        await self.sendMessage(chat_id=update.effective_message.chat_id, text=msgText, parse_mode='HTML')
        index = 0
        user = User.load(self.crawler.getUserDB(), str(update.effective_user.id))
        showCouponIndexText = False
        for coupon in coupons:
            if showCouponIndexText:
                additionalText = 'Coupon ' + str(index + 1) + '/' + str(len(coupons))
                await self.displayCouponWithImage(update=update, context=context, coupon=coupon, user=user, additionalText=additionalText)
            else:
                await self.displayCouponWithImage(update=update, context=context, coupon=coupon, user=user, additionalText=None)
            index += 1

    async def botDisplayOffers(self, update: Update, context: CallbackContext):
        """
        Posts all current offers (= photos with captions) into current chat.
        """
        activeOffers = self.crawler.getOffersActive()
        bkOffersOnWebsiteText = 'Vielleicht findest du auf der BK Webseite welche: ' + URLs.BK_KING_DEALS
        if len(activeOffers) == 0:
            # BK should always have offers but let's check for this case anyways.
            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN)]])
            menuText = SYMBOLS.WARNING + '<b>Es gibt derzeit keine Angebote im Bot!</b>'
            menuText += '\n' + bkOffersOnWebsiteText
            await self.editOrSendMessage(update, text=menuText, reply_markup=reply_markup, parse_mode='HTML', disable_web_page_preview=True)
            return CallbackVars.MENU_MAIN
        prePhotosText = f'<b>Es sind derzeit {len(activeOffers)} Angebote verfügbar:</b>'
        prePhotosText += '\n' + bkOffersOnWebsiteText
        await self.editOrSendMessage(update, text=prePhotosText, parse_mode='HTML', disable_web_page_preview=True)
        for offer in activeOffers:
            offerText = offer['title']
            subtitle = offer.get('subline')
            if subtitle is not None and len(subtitle) > 0:
                offerText += subtitle
            startDateStr = offer.get('start_date')
            if startDateStr is not None:
                offerText += '\nGültig ab ' + convertCouponAndOfferDateToGermanFormat(startDateStr)
            expirationDateStr = offer.get('expiration_date')
            if expirationDateStr is not None:
                offerText += '\nGültig bis ' + convertCouponAndOfferDateToGermanFormat(expirationDateStr)
            # This is a bit f*cked up but should work - offerIDs are not really unique but we'll compare the URL too and if the current URL is not in our cache we'll have to re-upload that file!
            sentMessage = await asyncio.create_task(self.sendPhoto(chat_id=update.effective_message.chat_id, photo=self.getOfferImage(offer), caption=offerText))
            # Save Telegram fileID pointing to that image in our cache
            self.offerImageCache.setdefault(couponOrOfferGetImageURL(offer), ImageCache(fileID=sentMessage.photo[0].file_id))

        menuText = '<b>Nix dabei?</b>'
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN),
                                              InlineKeyboardButton(SYMBOLS.ARROW_RIGHT + " Zu den Gutscheinen",
                                                                   callback_data="?a=dcs&m=" + CouponViews.ALL.getViewCode() + "&cs=")], []])
        await self.sendMessage(chat_id=update.effective_user.id, text=menuText, parse_mode='HTML', reply_markup=reply_markup, disable_web_page_preview=True)
        return CallbackVars.MENU_OFFERS

    async def botDisplayFeedbackCodes(self, update: Update, context: CallbackContext):
        """ 2021-07-15: New- and unfinished feature """
        numberOfFeedbackCodesToGenerate = 3
        text = f"\n<b>Hier sind {numberOfFeedbackCodesToGenerate} Feedback Codes für dich:</b>"
        for index in range(numberOfFeedbackCodesToGenerate):
            text += "\n" + generateFeedbackCode()
        text += "\nSchreibe einen Code deiner Wahl auf die Rückseite eines BK Kassenbons, um den gratis Artikel zu erhalten."
        text += "\nFalls weder Kassenbon noch Schamgefühl vorhanden sind, hier ein Trick:"
        text += "\nBestelle ein einzelnes Päckchen Mayo oder Ketchup für ~0,20€ und lasse dir den Kassenbon geben."
        text += "\nDie Konditionen der Feedback Codes variieren."
        text += "\nDerzeit gibt es: Gratis Eiswaffel oder Kaffee(klein) [Stand: 14.04.2021]"
        text += "\nDanke an <a href=\"https://edik.ch/posts/hack-the-burger-king.html\">Edik</a>!"
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN)]])
        await self.editOrSendMessage(update, text=text, reply_markup=reply_markup, parse_mode='HTML', disable_web_page_preview=True)
        return CallbackVars.MENU_FEEDBACK_CODES

    async def botDisplayMenuSettings(self, update: Update, context: CallbackContext):
        user = self.getUser(userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        await self.displaySettings(update, context, user)
        return CallbackVars.MENU_SETTINGS

    async def displaySettings(self, update: Update, context: CallbackContext, user: User):
        keyboard = []
        # TODO: Make this nicer
        dummyUser = User()
        userWantsAutodeleteOfFavoriteCoupons = user.settings.autoDeleteExpiredFavorites
        addedSettingCategories = []
        hasAddedEasterEggButton = False
        for settingKey, setting in USER_SETTINGS_ON_OFF.items():
            # All settings that are in 'USER_SETTINGS_ON_OFF' are simply on/off settings and will automatically be included in users' settings.
            settingCategory = USER_SETTINGS_ON_OFF[settingKey]["category"]
            # Add setting category button if it hasn't been added already
            if settingCategory not in addedSettingCategories:
                addedSettingCategories.append(settingCategory)
                if not hasAddedEasterEggButton and user.favoriteCoupons is not None and len(user.favoriteCoupons) > 0:
                    callback_data = CallbackVars.EASTER_EGG
                    hasAddedEasterEggButton = True
                else:
                    callback_data = 'DummyButtonSettingCategory'
                keyboard.append([InlineKeyboardButton(SYMBOLS.WHITE_DOWN_POINTING_BACKHAND * 2 + settingCategory.title + SYMBOLS.WHITE_DOWN_POINTING_BACKHAND * 2,
                                                      callback_data=callback_data)])
            description = USER_SETTINGS_ON_OFF[settingKey]["description"]
            # Check for special cases where one setting depends of the state of another
            if settingKey == 'notifyWhenFavoritesAreBack' and userWantsAutodeleteOfFavoriteCoupons:
                continue
            if user.settings.get(settingKey, dummyUser.settings[settingKey]):
                # Setting is currently enabled
                keyboard.append(
                    [InlineKeyboardButton(SYMBOLS.CONFIRM + description, callback_data=settingKey)])
            else:
                # Setting is currently disabled
                keyboard.append([InlineKeyboardButton(description, callback_data=settingKey)])
        addDeletePaybackCardButton = False
        if user.getPaybackCardNumber() is None:
            keyboard.append([InlineKeyboardButton(SYMBOLS.CIRLCE_BLUE + 'Payback Karte hinzufügen', callback_data=CallbackVars.MENU_SETTINGS_ADD_PAYBACK_CARD)])
        else:
            # Looks complicated but this is simply so that we can show all "delete buttons" in one row
            addDeletePaybackCardButton = True
        menuText = SYMBOLS.WRENCH + "<b>Einstellungen:</b>"
        menuText += "\nNicht alle Filialen nehmen alle Gutschein-Typen!\nPrüfe die Akzeptanz von App- bzw. Papiercoupons vorm Bestellen über den <a href=\"" + URLs.PROTOCOL_BK + URLs.BK_KING_FINDER + "\">KINGFINDER</a>."
        menuText += "\n*¹ Versteckte Coupons sind meist überteuerte große Menüs auch 'Upselling Artikel' genannt."
        if user.hasStoredSortModes():
            keyboard.append([InlineKeyboardButton(SYMBOLS.WARNING + "Gespeicherte Sortierungen löschen",
                                                  callback_data=CallbackVars.MENU_SETTINGS_RESET)])
            menuText += "\n---"
            menuText += f"\nEs gibt gespeicherte Coupon Sortierungen für {len(user.couponViewSortModes)} Coupon Ansichten, die beim Klick auf den zurücksetzen Button ebenfalls gelöscht werden."
        if not user.hasDefaultSettings():
            keyboard.append([InlineKeyboardButton(SYMBOLS.WARNING + "Einstell. zurücksetzen | PB Karte & " + SYMBOLS.STAR + " bleiben",
                                                  callback_data=CallbackVars.MENU_SETTINGS_RESET)])
        if addDeletePaybackCardButton:
            keyboard.append([InlineKeyboardButton(SYMBOLS.DENY + 'Payback Karte löschen', callback_data=CallbackVars.MENU_SETTINGS_DELETE_PAYBACK_CARD)])
        if len(user.favoriteCoupons) > 0:
            # Additional DB request required so let's only jump into this handling if the user has at least one favorite coupon.
            userFavoritesInfo = user.getUserFavoritesInfo(self.crawler.getFilteredCouponsAsDict(CouponViews.FAVORITES.getFilter()), sortCoupons=True)
            if len(userFavoritesInfo.couponsUnavailable) > 0:
                keyboard.append([InlineKeyboardButton(SYMBOLS.DENY + "Abgelaufene Favoriten löschen (" + str(len(userFavoritesInfo.couponsUnavailable)) + ")?*²",
                                                      callback_data=CallbackVars.MENU_SETTINGS_DELETE_UNAVAILABLE_FAVORITE_COUPONS)])
                menuText += "\n*²" + SYMBOLS.DENY + "Löschbare abgelaufene Favoriten:"
                menuText += "\n" + userFavoritesInfo.getUnavailableFavoritesText()
        keyboard.append([InlineKeyboardButton(SYMBOLS.DENY + SYMBOLS.DENY + "BetterKing Account löschen" + SYMBOLS.DENY + SYMBOLS.DENY,
                                              callback_data=CallbackVars.MENU_SETTINGS_USER_DELETE_ACCOUNT)])
        # Back button
        keyboard.append([InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN)])
        await self.editOrSendMessage(update=update, text=menuText, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)

    async def botDisplaySingleCoupon(self, update: Update, context: CallbackContext):
        query = update.callback_query
        await query.answer()
        callbackArgs = furl(query.data).args
        uniqueCouponID = callbackArgs['plu']
        callbackBack = callbackArgs['cb']
        coupon = Coupon.load(self.crawler.getCouponDB(), uniqueCouponID)
        user = User.load(self.crawler.getUserDB(), str(update.effective_user.id))
        # Send coupon image in chat
        await self.displayCouponWithImage(update, context, coupon, user)
        # Post user-menu into chat
        menuText = 'Coupon Details'
        if not user.settings.displayQR:
            menuText += '\n' + SYMBOLS.INFORMATION + 'Möchtest du QR-Codes angezeigt bekommen?\nSiehe Hauptmenü -> Einstellungen'
        await self.sendMessage(chat_id=update.effective_message.chat_id, text=menuText, parse_mode='HTML',
                               reply_markup=InlineKeyboardMarkup([[], [InlineKeyboardButton(SYMBOLS.BACK, callback_data=callbackBack)]]))
        # Delete previous message containing menu buttons from chat as we don't need it anymore.
        await context.bot.delete_message(chat_id=update.effective_message.chat_id, message_id=query.message.message_id)
        return CallbackVars.MENU_DISPLAY_COUPON

    async def botUserDeleteAccountSTART_COMMAND(self, update: Update, context: CallbackContext):
        await self.botUserDeleteAccountSTART(update, context, CallbackVars.MENU_MAIN)
        return CallbackVars.MENU_SETTINGS_USER_DELETE_ACCOUNT

    async def botUserDeleteAccountSTART_MENU(self, update: Update, context: CallbackContext):
        await self.botUserDeleteAccountSTART(update, context, CallbackVars.GENERIC_BACK)
        return CallbackVars.MENU_SETTINGS_USER_DELETE_ACCOUNT

    async def botUserDeleteAccountSTART(self, update: Update, context: CallbackContext, callbackBackButton: str):
        user = self.getUser(userID=update.effective_user.id, addIfNew=False)
        if user is None:
            menuText = f'{SYMBOLS.WARNING}Es existiert kein Benutzer mit der ID <b>{update.effective_user.id}</b> in der Datenbank.'
            menuText += '\nMit /start meldest du dich erstmalig an.'
            await self.editOrSendMessage(update, text=menuText, parse_mode='HTML')
        else:
            menuText = f'<b>\"Dann geh doch zu Netto!\"</b>\nAntworte mit deiner Benutzer-ID <b>{update.effective_user.id}</b>, um deine Benutzerdaten <b>endgültig</b> vom Server zu löschen.'
            await self.editOrSendMessage(update, text=menuText, parse_mode='HTML',
                                         reply_markup=InlineKeyboardMarkup([[], [InlineKeyboardButton("Doch nicht", callback_data=callbackBackButton)]]))

    async def botUserDeleteAccount(self, update: Update, context: CallbackContext):
        """ Deletes users' account from DB. """
        userInput = None if update.message is None else update.message.text
        if userInput is not None and userInput == str(update.effective_user.id):
            userDB = self.crawler.getUserDB()
            # Delete user from DB
            del userDB[str(update.effective_user.id)]
            menuText = SYMBOLS.CONFIRM + 'Dein BetterKing Account wurde vernichtet!'
            menuText += '\nDu kannst diesen Chat nun löschen.'
            menuText += '\n<b>Viel Erfolg beim Abnehmen!</b>'
            menuText += '\nIn loving memory of <i>blauelagunepb_mydealz</i> ' + SYMBOLS.HEART
            await self.editOrSendMessage(update, text=menuText, parse_mode='HTML')
            return ConversationHandler.END
        else:
            menuText = SYMBOLS.DENY + '<b>Falsche Antwort!</b>'
            menuText += f'\nDie richtige Antwort ist <b>{update.effective_user.id}</b>.'
            await self.editOrSendMessage(update, text=menuText, parse_mode='HTML',
                                         reply_markup=InlineKeyboardMarkup([[], [InlineKeyboardButton("Ich mag bleiben und fett werden", callback_data=CallbackVars.MENU_MAIN)]]))
            return CallbackVars.MENU_SETTINGS_USER_DELETE_ACCOUNT

    async def displayCouponWithImage(self, update: Update, context: CallbackContext, coupon: Coupon, user: User, additionalText: Union[str, None] = None):
        """
        Sends new message with coupon information & photo (& optionally coupon QR code) + "Save/Delete favorite" button in chat.
        """
        favoriteKeyboard = self.getCouponFavoriteKeyboard(user.isFavoriteCoupon(coupon), coupon.id, CallbackVars.COUPON_LOOSE_WITH_FAVORITE_SETTING)
        replyMarkupWithoutBackButton = InlineKeyboardMarkup([favoriteKeyboard, []])
        couponText = coupon.generateCouponLongTextFormattedWithDescription(highlightIfNew=True)
        if additionalText is not None:
            couponText += '\n' + additionalText
        if user.settings.displayQR:
            # We need to send two images -> Send as album
            photoCoupon = InputMediaPhoto(media=self.getCouponImage(coupon), caption=couponText, parse_mode='HTML')
            photoQR = InputMediaPhoto(media=self.getCouponImageQR(coupon), caption=couponText, parse_mode='HTML')
            # await self.sendMediaGroup(chat_id=update.effective_message.chat_id, media=[photoCoupon, photoQR])
            chatMessages = await asyncio.create_task(self.sendMediaGroup(chat_id=update.effective_message.chat_id, media=[photoCoupon, photoQR]))
            msgCoupon = chatMessages[0]
            msgQR = chatMessages[1]
            # Add to cache if not already present
            self.couponImageQRCache.setdefault(coupon.id, ImageCache(fileID=msgQR.photo[0].file_id))
            await self.sendMessage(chat_id=update.effective_message.chat_id, text=couponText, parse_mode='HTML', reply_markup=replyMarkupWithoutBackButton,
                                   disable_web_page_preview=True)
        else:
            msgCoupon = await asyncio.create_task(self.sendPhoto(chat_id=update.effective_message.chat_id, photo=self.getCouponImage(coupon), caption=couponText, parse_mode='HTML',
                                                                 reply_markup=replyMarkupWithoutBackButton))
        # Add to cache if not already present
        self.couponImageCache.setdefault(coupon.id, ImageCache(fileID=msgCoupon.photo[0].file_id))
        return CallbackVars.COUPON_LOOSE_WITH_FAVORITE_SETTING

    async def botCouponToggleFavorite(self, update: Update, context: CallbackContext):
        """ Toggles coupon favorite state and edits reply_markup accordingly so user gets to see the new state of this setting. """
        query = update.callback_query
        await query.answer()
        uniqueCouponID = re.search(PATTERN.PLU_TOGGLE_FAV, update.callback_query.data).group(1)
        userDB = self.crawler.getUserDB()
        user = getUserFromDB(userDB=userDB, userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)

        if uniqueCouponID in user.favoriteCoupons:
            # Delete coupon from favorites
            user.deleteFavoriteCouponID(uniqueCouponID)
            isFavorite = False
        else:
            # Add coupon to favorites if it still exists in our DB
            coupon = Coupon.load(self.crawler.getCouponDB(), uniqueCouponID)
            if coupon is None:
                # Edge case: Coupon may have been deleted from DB while user had this keyboard open.
                await self.editOrSendMessage(update, text=SYMBOLS.WARNING + 'Coupon Favoritenstatus kann nicht geändert werden, da dieser Coupon nicht mehr existiert!',
                                             parse_mode='HTML')
                return CallbackVars.COUPON_LOOSE_WITH_FAVORITE_SETTING
            user.addFavoriteCoupon(coupon)
            isFavorite = True
        # Update DB
        user.store(userDB)
        favoriteKeyboard = self.getCouponFavoriteKeyboard(isFavorite, uniqueCouponID, CallbackVars.COUPON_LOOSE_WITH_FAVORITE_SETTING)
        replyMarkupWithoutBackButton = InlineKeyboardMarkup([favoriteKeyboard, []])
        await query.edit_message_reply_markup(reply_markup=replyMarkupWithoutBackButton)
        return CallbackVars.COUPON_LOOSE_WITH_FAVORITE_SETTING

    def getCouponFavoriteKeyboard(self, isFavorite: bool, uniqueCouponID: str, callbackBack: str) -> list:
        """
        Returns an InlineKeyboardButton button array containing a single favorite save/delete button depending on the current favorite state.
        """
        favoriteKeyboard = []
        if isFavorite:
            favoriteKeyboard.append(InlineKeyboardButton(SYMBOLS.DENY + ' Favorit entfernen', callback_data='plu,' + uniqueCouponID + ',togglefav,' + callbackBack))
        else:
            favoriteKeyboard.append(InlineKeyboardButton(SYMBOLS.STAR + ' Favorit speichern', callback_data='plu,' + uniqueCouponID + ',togglefav,' + callbackBack))
        return favoriteKeyboard

    def generateCouponShortTextWithHyperlinkToChannelPost(self, coupon: Coupon, messageID: int) -> str:
        """ Returns e.g. "Y15 | 2Whopper+M🍟+0,4Cola (https://t.me/betterkingpublic/1054) | 8,99€" """
        text = "<b>" + coupon.getPLUOrUniqueID() + "</b> | <a href=\"https://t.me/" + self.getPublicChannelName() + '/' + str(
            messageID) + "\">" + coupon.getTitleShortened(includeVeggieSymbol=True) + "</a>"
        priceFormatted = coupon.getPriceFormatted()
        if priceFormatted is not None:
            text += " | " + priceFormatted
        return text

    def getFilteredCouponsAsList(self, couponFilter: CouponFilter, sortIfSortCodeIsGivenInCouponFilter: bool = True) -> list:
        """  Wrapper for crawler.filterCouponsList with errorhandling when no coupons are available. """
        coupons = self.crawler.getFilteredCouponsAsList(couponFilter, sortIfSortCodeIsGivenInCouponFilter=sortIfSortCodeIsGivenInCouponFilter)
        self.checkForNoCoupons(coupons)
        return coupons

    def getFilteredCouponsAsDict(self, couponFilter: CouponFilter, sortIfSortCodeIsGivenInCouponFilter: bool = True) -> dict:
        """  Wrapper for crawler.filterCouponsList with errorhandling when no coupons are available. """
        coupons = self.crawler.getFilteredCouponsAsDict(couponFilter, sortIfSortCodeIsGivenInCouponFilter)
        self.checkForNoCoupons(coupons)
        return coupons

    def checkForNoCoupons(self, coupons: Union[dict, list]):
        if len(coupons) == 0:
            menuText = SYMBOLS.DENY + ' <b>Es gibt derzeit keine Coupons in den von dir ausgewählten Kategorien und/oder in Kombination mit den eingestellten Filtern!</b>'
            raise BetterBotException(menuText, InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.MENU_MAIN)]]))

    def getCouponImage(self, coupon: Coupon):
        """ Returns either image URL or file or Telegram file_id of a given coupon. """
        cachedImageData = self.couponImageCache.get(coupon.id)
        """ Re-use Telegram file-ID if possible: https://core.telegram.org/bots/api#message
        According to the Telegram FAQ, such file_ids can be trusted to be persistent: https://core.telegram.org/bots/faq#can-i-count-on-file-ids-to-be-persistent """
        imagePath = coupon.getImagePath()
        if cachedImageData is not None:
            # Re-use cached image_id and update cache timestamp
            cachedImageData.updateLastUsedTimestamp()
            logging.debug("Returning coupon image file_id: " + cachedImageData.imageFileID)
            return cachedImageData.imageFileID
        elif isValidImageFile(imagePath):
            # Return image file
            logging.debug("Returning coupon image file in path: " + imagePath)
            return open(imagePath, mode='rb')
        else:
            # Return fallback image file -> Should usually not be required!
            logging.warning("Returning coupon fallback image for path: " + imagePath)
            return open("media/fallback_image_missing_coupon_image.jpeg", mode='rb')

    def getCouponImageQR(self, coupon: Coupon):
        """ Returns either image URL or file or Telegram file_id of a given coupon QR image. """
        cachedQRImageData = self.couponImageQRCache.get(coupon.id)
        # Re-use Telegram file-ID if possible: https://core.telegram.org/bots/api#message
        if cachedQRImageData is not None:
            # Return cached image_id and update cache timestamp
            cachedQRImageData.updateLastUsedTimestamp()
            logging.debug("Returning QR image file_id: " + cachedQRImageData.imageFileID)
            return cachedQRImageData.imageFileID
        else:
            # Return image
            logging.debug("Returning QR image file")
            return coupon.getImageQR()

    def getOfferImage(self, offer: dict):
        """ Returns either image URL or file or Telegram file_id of a given offer. """
        image_url = couponOrOfferGetImageURL(offer)
        cachedImageData = self.offerImageCache.get(image_url)
        if cachedImageData is not None:
            # Re-use cached image_id and update cache timestamp
            cachedImageData.updateLastUsedTimestamp()
            return cachedImageData.imageFileID
        if os.path.exists(offerGetImagePath(offer)):
            # Return image file
            return open(offerGetImagePath(offer), mode='rb')
        else:
            # Fallback -> Shouldn't be required!
            return open('media/fallback_image_missing_offer_image.jpeg', mode='rb')

    async def botDisplaySettingsToggleSetting(self, update: Update, context: CallbackContext):
        """ Toggles pre-selected setting via settingKey. """
        await update.callback_query.answer()
        settingKey = update.callback_query.data
        userDB = self.crawler.getUserDB()
        dummyUser = User()
        user = getUserFromDB(userDB=userDB, userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        if user.settings.get(settingKey, dummyUser.settings[settingKey]):
            user.settings[settingKey] = False
        else:
            user.settings[settingKey] = True
        user.store(userDB)
        await self.displaySettings(update, context, user)
        return CallbackVars.MENU_SETTINGS

    async def botResetSortSettings(self, update: Update, context: CallbackContext):
        """ Resets users' settings to default """
        userDB = self.crawler.getUserDB()
        user = getUserFromDB(userDB=userDB, userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        user.couponViewSortModes = {}
        # Update DB
        user.store(userDB)
        # Reload settings menu
        await self.displaySettings(update, context, user)
        return CallbackVars.MENU_SETTINGS

    async def botResetSettings(self, update: Update, context: CallbackContext):
        """ Resets users' settings to default """
        userDB = self.crawler.getUserDB()
        user = getUserFromDB(userDB=userDB, userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        user.resetSettings()
        # Update DB
        user.store(userDB)
        # Reload settings menu
        await self.displaySettings(update, context, user)
        return CallbackVars.MENU_SETTINGS

    async def botDeleteUnavailableFavoriteCoupons(self, update: Update, context: CallbackContext):
        """ Removes all user selected favorites which are unavailable/expired at this moment. """
        userDB = self.crawler.getUserDB()
        user = getUserFromDB(userDB=userDB, userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        await self.deleteUsersUnavailableFavorites(userDB, [user])
        await self.displaySettings(update, context, user)
        return CallbackVars.MENU_SETTINGS

    async def botAddPaybackCard(self, update: Update, context: CallbackContext):
        if update.message is None or update.message.text is None:
            # No user input -> Ask for input
            text = 'Antworte mit deiner Payback Kartennummer (EAN, 13-stellig) oder Kundennummer (10-stellig), um deine Karte hinzuzufügen.'
            text += '\nDiese Daten werden ausschließlich gespeichert, um dir deine Payback Karte im Bot anzeigen zu können.'
            text += '\nDu kannst deine Karte in den Einstellungen jederzeit aus dem Bot löschen.'
            await self.editOrSendMessage(update, text=text, parse_mode='HTML',
                                         reply_markup=InlineKeyboardMarkup([[], [InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.GENERIC_BACK)]]))
            return CallbackVars.MENU_SETTINGS_ADD_PAYBACK_CARD
        userInput = update.message.text
        if userInput.isdecimal() and (len(userInput) == 10 or len(userInput) == 13):
            # Valid user input
            if len(userInput) == 13:
                paybackCardNumber = userInput[3:13]
            else:
                paybackCardNumber = userInput
            userDB = self.crawler.getUserDB()
            user = getUserFromDB(userDB=userDB, userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
            user.addPaybackCard(paybackCardNumber=paybackCardNumber)
            user.store(userDB)
            text = SYMBOLS.CONFIRM + 'Deine Payback Karte wurde eingetragen.'
            await self.sendMessage(chat_id=update.effective_user.id, text=text)
            await self.displayPaybackCard(update=update, context=context, user=user)
            return CallbackVars.MENU_DISPLAY_PAYBACK_CARD
        else:
            # Invalid user input
            await self.sendMessage(chat_id=update.effective_user.id, text=SYMBOLS.DENY + 'Ungültige Eingabe!', parse_mode='HTML',
                                   reply_markup=InlineKeyboardMarkup([[], [InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.GENERIC_BACK)]]))
            return CallbackVars.MENU_SETTINGS_ADD_PAYBACK_CARD

    async def botDeletePaybackCard(self, update: Update, context: CallbackContext):
        """ Deletes Payback card from users account if his answer is matching his Payback card number. """
        # Validate input
        userDB = self.crawler.getUserDB()
        user = getUserFromDB(userDB, userID=update.effective_user.id, addIfNew=False, updateUsageTimestamp=True)
        paybackCardNumber = user.getPaybackCardNumber()
        if paybackCardNumber is None:
            # This should never happen!
            await self.editOrSendMessage(update, text=f'{SYMBOLS.DENY} Du hast keine Payback Karte!', parse_mode='HTML',
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.GENERIC_BACK)]]))
            return CallbackVars.MENU_SETTINGS_DELETE_PAYBACK_CARD
        userInput = None if update.message is None else update.message.text
        if userInput is None:
            await self.editOrSendMessage(update, text='Antworte mit deiner Payback Kartennummer <b>' + paybackCardNumber + '</b>, um diese zu löschen.',
                                         parse_mode='HTML',
                                         reply_markup=InlineKeyboardMarkup([[], [InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.GENERIC_BACK)]]))
        elif userInput == paybackCardNumber:
            user.deletePaybackCard()
            user.store(userDB)
            text = SYMBOLS.CONFIRM + 'Payback Karte ' + userInput + ' wurde gelöscht.'
            await self.editOrSendMessage(update, text=text,
                                         parse_mode='HTML',
                                         reply_markup=InlineKeyboardMarkup([[], [InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.GENERIC_BACK)]]))
        else:
            await self.editOrSendMessage(update, text=SYMBOLS.DENY + 'Ungültige Eingabe!', parse_mode='HTML',
                                         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.GENERIC_BACK)]]))
        return CallbackVars.MENU_SETTINGS_DELETE_PAYBACK_CARD

    async def botDisplayPaybackCard(self, update: Update, context: CallbackContext):
        user = self.getUser(userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        query = update.callback_query
        if query is not None:
            await query.answer()
        await self.displayPaybackCard(update, context, user)
        return CallbackVars.MENU_DISPLAY_PAYBACK_CARD

    async def displayPaybackCard(self, update: Update, context: CallbackContext, user: User):
        if user.getPaybackCardNumber() is None:
            text = SYMBOLS.WARNING + 'Du hast noch keine Payback Karte eingetragen!'
            reply_markup = InlineKeyboardMarkup([[], [InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.GENERIC_BACK),
                                                      InlineKeyboardButton(SYMBOLS.PLUS + 'Karte hinzufügen', callback_data=CallbackVars.MENU_SETTINGS_ADD_PAYBACK_CARD)]])
            await self.editOrSendMessage(update, text=text, parse_mode='html',
                                         reply_markup=reply_markup)
        else:
            text = 'Payback Kartennummer: <b>' + splitStringInPairs(user.getPaybackCardNumber()) + '</b>'
            text += '\n<b>Tipp:</b> Pinne diese Nachricht an, um im Bot Chat noch einfacher auf deine Payback Karte zugreifen zu können.'
            replyMarkup = InlineKeyboardMarkup([[InlineKeyboardButton(SYMBOLS.BACK, callback_data=CallbackVars.GENERIC_BACK),
                                                 InlineKeyboardButton(SYMBOLS.DENY + 'Karte löschen', callback_data=CallbackVars.MENU_SETTINGS_DELETE_PAYBACK_CARD)]])
            await self.sendPhoto(chat_id=update.effective_user.id, photo=user.getPaybackCardImage(), caption=text, parse_mode='html', disable_notification=True,
                                 reply_markup=replyMarkup)
        return CallbackVars.MENU_DISPLAY_PAYBACK_CARD

    async def botAdminToggleMaintenanceMode(self, update: Update, context: CallbackContext):
        user = getUserFromDB(userDB=self.crawler.getUserDB(), userID=update.effective_user.id, addIfNew=True, updateUsageTimestamp=True)
        self.adminOrException(user)
        if self.maintenanceMode:
            # Remove all handlers
            for handlerList in self.application.handlers.values():
                for handler in handlerList:
                    self.application.remove_handler(handler)
            # RE-init handlers so bot behaves normal again
            self.initHandlers()
            self.maintenanceMode = False
            await self.sendMessage(chat_id=update.effective_user.id, text=SYMBOLS.CONFIRM + 'Wartungsmodus deaktiviert.')
        else:
            # Change callback of all handlers to point to maintenance function
            for handlerList in self.application.handlers.values():
                for handler in handlerList:
                    all_handlers: List = []
                    try:
                        # Not all types of handlers have all properties
                        all_handlers.extend(handler.entry_points)
                        all_handlers.extend(handler.fallbacks)
                        for handlers in handler.states.values():
                            all_handlers.extend(handlers)
                    except AttributeError:
                        pass
                    for thishandler in all_handlers:
                        """ Make sure not to disable the maintenance command itself otherwise the bot will be stuck in maintenance mode forever ;) """
                        if isinstance(thishandler, CommandHandler) and Commands.MAINTENANCE in thishandler.commands:
                            continue
                        thishandler.callback = self.botDisplayMaintenanceMode
            self.maintenanceMode = True
            await self.sendMessage(chat_id=update.effective_user.id, text=SYMBOLS.CONFIRM + 'Wartungsmodus aktiviert.')
        return None

    async def batchProcessAutoDeleteUsersUnavailableFavorites(self):
        """ Deletes expired favorite coupons of all users who enabled auto deletion of those. """
        userDB = self.crawler.getUserDB()
        users = []
        for userIDStr in userDB:
            user = User.load(userDB, userIDStr)
            if user.settings.autoDeleteExpiredFavorites:
                users.append(user)
        await self.deleteUsersUnavailableFavorites(userDB, users)

    async def deleteUsersUnavailableFavorites(self, userDB: Database, users: list):
        """ Deletes expired favorite coupons of all users who enabled auto deletion of those. """
        coupons = self.getFilteredCouponsAsDict(couponFilter=CouponFilter())
        dbUpdates = []
        for user in users:
            userUnavailableFavoriteCouponInfo = user.getUserFavoritesInfo(couponsFromDB=coupons, sortCoupons=False)
            if len(userUnavailableFavoriteCouponInfo.couponsUnavailable) > 0:
                for unavailableCoupon in userUnavailableFavoriteCouponInfo.couponsUnavailable:
                    user.deleteFavoriteCouponID(unavailableCoupon.id)
                dbUpdates.append(user)
        if len(dbUpdates) > 0:
            logging.info('Deleting expired favorites of ' + str(len(dbUpdates)) + ' users')
            userDB.update(dbUpdates)

    def getNewCouponsTextWithChannelHyperlinks(self, couponsDict: dict, maxNewCouponsToLink: int) -> str:
        infoText = ''
        """ Add detailed information about added coupons. Limit the max. number of that so our information message doesn't get too big. """
        index = 0
        channelDB = self.couchdb[DATABASES.TELEGRAM_CHANNEL]
        for uniqueCouponID in couponsDict:
            coupon = couponsDict[uniqueCouponID]

            """ Generates e.g. "Y15 | 2Whopper+M🍟+0,4LCola | 8,99€"
            Returns the same with hyperlink if a chat_id is given for this coupon e.g.:
            "Y15 | 2Whopper+M🍟+0,4LCola (https://t.me/betterkingpublic/1054) | 8,99€"
            """
            if coupon.id in channelDB:
                channelCoupon = ChannelCoupon.load(channelDB, coupon.id)
                messageID = channelCoupon.getMessageIDForChatHyperlink()
                if messageID is not None:
                    couponText = coupon.generateCouponShortTextFormattedWithHyperlinkToChannelPost(highlightIfNew=False, includeVeggieSymbol=True,
                                                                                                   publicChannelName=self.getPublicChannelName(),
                                                                                                   messageID=messageID)
                else:
                    # This should never happen but we'll allow it to
                    logging.warning("Can't hyperlink coupon because no messageIDs available: " + coupon.id)
                    couponText = coupon.generateCouponShortTextFormatted(highlightIfNew=False)
            else:
                # This should never happen but we'll allow it to anyways
                logging.warning("Can't hyperlink coupon because it is not in channelDB: " + coupon.id)
                couponText = coupon.generateCouponShortTextFormatted(highlightIfNew=False)
            infoText += '\n' + couponText

            if index == maxNewCouponsToLink - 1:
                # We processed the max. number of allowed items!
                break
            else:
                index += 1
                continue
        if len(couponsDict) > maxNewCouponsToLink:
            numberOfNonHyperinkedItems = len(couponsDict) - maxNewCouponsToLink
            if numberOfNonHyperinkedItems == 1:
                infoText += '\n+ ' + str(numberOfNonHyperinkedItems) + ' weiterer'
            else:
                infoText += '\n+ ' + str(numberOfNonHyperinkedItems) + ' weitere'
        return infoText

    def deleteInactiveAccounts(self) -> None:
        """ Deletes all inactive accounts from DB and informs user about that account deletion. """
        usersToDelete = []
        userDB = self.crawler.getUserDB()
        for userID in userDB:
            user = User.load(userDB, userID)
            if user.isEligableForAutoDeletion():
                usersToDelete.append(user)
                try:
                    text = SYMBOLS.WARNING + '<b>Dein BetterKing Account wurde wegen Inaktivität gelöscht.</b>'
                    text += f'\nDu hast ihn zuletzt verwendet vor: {formatSeconds(seconds=user.getSecondsPassedSinceLastTimeUsed())}'
                    self.sendMessage(chat_id=userID, text=text, parse_mode='HTML')
                except:
                    traceback.print_exc()
                    logging.info(f'Error while notifying user {userID} about auto account deletion.')
                    pass
        if len(usersToDelete) > 0:
            logging.info(f'Deleting {len(usersToDelete)} inactive users from DB')
            userDB.purge(docs=usersToDelete)
        pass

    async def batchProcess(self):
        """ Runs all processes which should only run once per day. """
        logging.info('Running batch process...')
        self.crawl()
        if self.getPublicChannelName() is not None:
            await self.renewPublicChannel()
        self.deleteInactiveAccounts()
        await self.batchProcessAutoDeleteUsersUnavailableFavorites()
        await self.notifyUsers()
        if self.getPublicChannelName() is not None:
            await self.cleanupPublicChannel()
        await self.cleanupCaches()
        logging.info('Batch process done')

    def crawl(self):
        try:
            self.crawler.crawlAndProcessData()
        except:
            traceback.print_exc()
            logging.warning("Crawler failed")

    async def notifyUsers(self):
        """ Notify users about expired favorite coupons that are back or new coupons depending on their settings. """
        try:
            await notifyUsersAboutNewCoupons(self)
            await notifyUsersAboutUpcomingAccountDeletion(self)
        except Exception:
            # This should never happen
            traceback.print_exc()
            logging.warning("Exception happened during user notify")

    async def renewPublicChannel(self):
        """ Deletes all channel messages and re-sends them / updates channel with current content. """
        try:
            await updatePublicChannel(self, updateMode=ChannelUpdateMode.RESEND_ALL)
        except Exception:
            traceback.print_exc()
            logging.warning("Renew of public channel failed")

    async def resumePublicChannelUpdate(self):
        """ Resumes channel update. """
        try:
            await updatePublicChannel(self, updateMode=ChannelUpdateMode.RESUME_CHANNEL_UPDATE)
        except Exception:
            traceback.print_exc()
            logging.warning("Resume of public channel update failed")

    async def cleanupPublicChannel(self):
        try:
            await cleanupChannel(self)
        except:
            traceback.print_exc()
            logging.warning("Cleanup channel failed")

    def startBot(self):
        self.application.run_polling()

    def stopBot(self):
        self.application.stop()

    async def cleanupCaches(self):
        logging.info('Cleanup caches...')
        await cleanupCache(self.couponImageCache)
        await cleanupCache(self.couponImageQRCache)
        await cleanupCache(self.offerImageCache)

    async def sendCouponOverviewWithChannelLinks(self, chat_id: Union[int, str], coupons: dict, useLongCouponTitles: bool, channelDB: Database, infoDB: Union[None, Database],
                                                 infoDBDoc: Union[None, InfoEntry]):
        """ Sends all given coupons to given chat_id separated by source and split into multiple messages as needed. """
        couponsSeparatedByType = getCouponsSeparatedByType(coupons)
        if infoDBDoc is not None:
            # Mark old coupon overview messageIDs for deletion
            oldCategoryMsgIDs = infoDBDoc.getAllCouponCategoryMessageIDs()
            if len(oldCategoryMsgIDs) > 0:
                logging.info("Saving coupon category messageIDs for deletion: " + str(oldCategoryMsgIDs))
                infoDBDoc.addMessageIDsToDelete(oldCategoryMsgIDs)
                infoDBDoc.deleteAllCouponCategoryMessageIDs()
                # Update DB
                infoDBDoc.store(infoDB)
        """ Re-send coupon overview(s), spread this information on multiple pages if needed. """
        couponOverviewCounter = 1
        for couponType, coupons in couponsSeparatedByType.items():
            couponCategory = CouponCategory(coupons)
            logging.info("Working on coupon overview " + str(couponOverviewCounter) + "/" + str(len(couponsSeparatedByType)) + " | " + couponCategory.namePluralWithoutSymbol)
            hasAddedSeparatorAfterCouponsWithoutMenu = False
            listContainsAtLeastOneItemWithoutMenu = False
            # Depends on the max entities per post limit of Telegram and we're not only using hyperlinks but also the "<b>" tag so we do not have 50 hyperlinks left but 49.
            maxCouponsPerPage = 49
            maxPage = math.ceil(len(coupons) / maxCouponsPerPage)
            for page in range(1, maxPage + 1):
                logging.info("Sending category page: " + str(page) + "/" + str(maxPage))
                couponOverviewText = couponCategory.getCategoryInfoText()
                if maxPage > 1:
                    couponOverviewText += "<b>Teil " + str(page) + "/" + str(maxPage) + "</b>"
                couponOverviewText += '\n---'
                # Calculate in which range the coupons of our current page are
                startIndex = page * maxCouponsPerPage - maxCouponsPerPage
                for couponIndex in range(startIndex, startIndex + maxCouponsPerPage):
                    coupon = coupons[couponIndex]
                    """ Add a separator so it is easier for the user to distinguish between coupons with- and without menu. 
                    This only works as "simple" as that because we pre-sorted these coupons!
                    """
                    if not coupon.isContainsFriesAndDrink():
                        listContainsAtLeastOneItemWithoutMenu = True
                    elif not hasAddedSeparatorAfterCouponsWithoutMenu and listContainsAtLeastOneItemWithoutMenu:
                        couponOverviewText += '\n<b>' + SYMBOLS.WHITE_DOWN_POINTING_BACKHAND + couponCategory.namePluralWithoutSymbol + ' mit Menü' + SYMBOLS.WHITE_DOWN_POINTING_BACKHAND + '</b>'
                        hasAddedSeparatorAfterCouponsWithoutMenu = True
                    """ Generates e.g. "Y15 | 2Whopper+M🍟+0,4LCola | 8,99€"
                    Returns the same with hyperlink if a chat_id is given for this coupon e.g.:
                    "Y15 | 2Whopper+M🍟+0,4LCola (https://t.me/betterkingpublic/1054) | 8,99€"
                    """
                    if coupon.id in channelDB:
                        channelCoupon = ChannelCoupon.load(channelDB, coupon.id)
                        messageID = channelCoupon.getMessageIDForChatHyperlink()
                        if messageID is not None:
                            if useLongCouponTitles:
                                couponText = coupon.generateCouponLongTextFormattedWithHyperlinkToChannelPost(self.getPublicChannelName(), messageID)
                            else:
                                couponText = coupon.generateCouponShortTextFormattedWithHyperlinkToChannelPost(highlightIfNew=True,
                                                                                                               publicChannelName=self.getPublicChannelName(),
                                                                                                               messageID=messageID, includeVeggieSymbol=True)
                        else:
                            # This should never happen but we'll allow it to
                            logging.warning("Can't hyperlink coupon because no messageIDs available: " + coupon.id)
                            if useLongCouponTitles:
                                couponText = coupon.generateCouponLongTextFormatted()
                            else:
                                couponText = coupon.generateCouponShortTextFormatted(highlightIfNew=True)
                    else:
                        # This should never happen but we'll allow it to
                        logging.warning("Can't hyperlink coupon because it is not in channelDB: " + coupon.id)
                        if useLongCouponTitles:
                            couponText = coupon.generateCouponLongTextFormatted()
                        else:
                            couponText = coupon.generateCouponShortTextFormatted(highlightIfNew=True)

                    couponOverviewText += '\n' + couponText
                    # Exit loop after last coupon info has been added
                    if couponIndex == len(coupons) - 1:
                        break
                # Send new post containing current page
                msg = await asyncio.create_task(self.sendMessage(chat_id=chat_id, text=couponOverviewText, parse_mode="HTML", disable_web_page_preview=True,
                                                                 disable_notification=True))
                if infoDBDoc is not None:
                    # Update DB
                    infoDBDoc.addCouponCategoryMessageID(couponType, msg.message_id)
                    infoDBDoc.lastMaintenanceModeState = self.maintenanceMode
                    infoDBDoc.store(infoDB)
            couponOverviewCounter += 1
        return

    async def deleteMessages(self, chat_id: Union[int, str], messageIDs: Union[List[int], None]):
        """ Deletes array of messageIDs. """
        if messageIDs is None:
            return
        index = 0
        for msgID in messageIDs:
            logging.info("Deleting message " + str(index + 1) + "/" + str(len(messageIDs)) + " | " + str(msgID))
            await self.deleteMessage(chat_id=chat_id, messageID=msgID)
            index += 1

    async def editOrSendMessage(self, update: Update, text: str, parse_mode: str = None, reply_markup: ReplyMarkup = None, disable_web_page_preview: bool = False,
                                disable_notification=False):
        """ Edits last message if possible. Sends new message otherwise.
         Usable for message with text-content only!
         Returns:
        :class:`telegram.Message`: On success, if edited message is sent by the bot, the
        edited Message is returned, otherwise :obj:`True` is returned.
        """
        query = update.callback_query
        if query is not None and query.message.text is not None:
            await query.answer()
            return await query.edit_message_text(text=text, parse_mode=parse_mode, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview)
        else:
            return await self.sendMessage(chat_id=update.effective_user.id, text=text, parse_mode=parse_mode, reply_markup=reply_markup,
                                          disable_web_page_preview=disable_web_page_preview, disable_notification=disable_notification)

    async def editMessage(self, chat_id: Union[int, str], message_id: Union[int, str], text: str, parse_mode: str = None, disable_web_page_preview: bool = False):
        await self.application.updater.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, parse_mode=parse_mode,
                                                             disable_web_page_preview=disable_web_page_preview)

    async def sendMessage(self, chat_id: Union[int, str], text: Union[str, None] = None, parse_mode: Union[None, str] = None,
                          disable_notification: ODVInput[bool] = DEFAULT_NONE, disable_web_page_preview: Union[bool, None] = None,
                          reply_markup: ReplyMarkup = None
                          ) -> Message:
        """ Wrapper """
        return await self.processMessage(chat_id=chat_id, text=text, parse_mode=parse_mode, disable_notification=disable_notification,
                                         disable_web_page_preview=disable_web_page_preview,
                                         reply_markup=reply_markup)

    async def sendPhoto(self, chat_id: Union[int, str], photo, caption: Union[None, str] = None,
                        parse_mode: Union[None, str] = None, disable_notification: ODVInput[bool] = DEFAULT_NONE,
                        reply_markup: 'ReplyMarkup' = None) -> Message:
        """ Wrapper """
        return await self.processMessage(chat_id=chat_id, photo=photo, caption=caption, parse_mode=parse_mode, disable_notification=disable_notification, reply_markup=reply_markup)

    async def sendMediaGroup(self, chat_id: Union[int, str], media: List, disable_notification: ODVInput[bool] = DEFAULT_NONE) -> List[Message]:
        """ Wrapper """
        return await self.processMessage(chat_id=chat_id, media=media, disable_notification=disable_notification)

    async def processMessage(self, chat_id: Union[int, str], maxTries: int = 20, text: Union[str, None] = None, parse_mode: Union[None, str] = None,
                             disable_notification: ODVInput[bool] = DEFAULT_NONE, disable_web_page_preview: Union[bool, None] = None,
                             reply_markup: 'ReplyMarkup' = None,
                             media: Union[None, List] = None,
                             photo=None, caption: Union[None, str] = None
                             ) -> Union[Message, List[Message]]:
        """ This will take care of "flood control exceeded" API errors (RetryAfter Errors). """
        retryNumber = 0
        lastException = None
        while retryNumber <= maxTries:
            try:
                retryNumber += 1
                if media is not None:
                    # Multiple photos/media
                    return await self.application.updater.bot.sendMediaGroup(chat_id=chat_id, disable_notification=disable_notification, media=media)
                elif photo is not None:
                    # Photo
                    return await self.application.updater.bot.send_photo(chat_id=chat_id, disable_notification=disable_notification, parse_mode=parse_mode, photo=photo,
                                                                         reply_markup=reply_markup,
                                                                         caption=caption
                                                                         )
                else:
                    # Text message
                    return await self.application.updater.bot.send_message(chat_id=chat_id, disable_notification=disable_notification, text=text, parse_mode=parse_mode,
                                                                           reply_markup=reply_markup,
                                                                           disable_web_page_preview=disable_web_page_preview)
            except RetryAfter as retryError:
                # https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this
                lastException = retryError
                """ Rate-Limit errorhandling: Wait some time and try again (one retry should do the job) """
                logging.info("Rate limit reached, waiting " + str(retryError.retry_after) + " seconds | Try number: " + str(retryNumber))
                await asyncio.sleep(retryError.retry_after)
                continue
            except BadRequest as requesterror:
                if requesterror.message == 'Group send failed':
                    # 2021-08-17: For unknown reasons this keeps happening sometimes...
                    # 2021-08-31: Seems like this is also some kind of rate limit or the same as the other one but no retry_after value given...
                    lastException = requesterror
                    waitseconds = 5
                    logging.info("Group send failed, waiting " + str(waitseconds) + " seconds | Try number: " + str(retryNumber))
                    await asyncio.sleep(waitseconds)
                    continue
                else:
                    raise requesterror
        raise lastException

    async def deleteMessage(self, chat_id: Union[int, str], messageID: Union[int, None]):
        if messageID is None:
            return
        try:
            await self.application.updater.bot.delete_message(chat_id=chat_id, message_id=messageID)
        except BadRequest:
            """ Typically this means that this message has already been deleted """
            logging.warning("Failed to delete message with message_id: " + str(messageID))

    def getUser(self, userID: Union[int, str], addIfNew: bool = False, updateUsageTimestamp: bool = False) -> User:
        """ Wrapper. Only call this if you do not wish to write to the userDB in the calling methods otherwise you're wasting resources! """
        return getUserFromDB(self.crawler.getUserDB(), userID, addIfNew=addIfNew, updateUsageTimestamp=updateUsageTimestamp)


async def runDaily(hour: int, minute: int, func: Coroutine):
    """ Runs task daily at specific time.
     Does not catch up run if desired time has already passed on the day this is executed first time.
     """
    while True:
        now = datetime.now()
        todayAtTargetTime = datetime(now.year, now.month, now.day, hour, minute)
        timediffToday = todayAtTargetTime - now
        if timediffToday.total_seconds() >= 0:
            print(f"Daily batch execution will happen at {hour}:{minute} TODAY in {timediffToday}")
            await asyncio.sleep(timediffToday.total_seconds())
        else:
            # Target time was already today -> Wait for same time next day
            tomorrowAtTargetTime = todayAtTargetTime + timedelta(days=1)
            timediffTomorrow = tomorrowAtTargetTime - now
            print(f"Daily batch execution will happen at {hour}:{minute} TOMORROW in {timediffTomorrow}")
            await asyncio.sleep(timediffTomorrow.total_seconds())
        await func


def main():
    bkbot: BKBot = BKBot()
    # Check for start-args to be executed immediately
    if bkbot.args.crawl:
        bkbot.crawl()
    loop = asyncio.get_event_loop()
    # Check for start args for stuff that can be executed in async way
    if bkbot.args.forcechannelupdatewithresend:
        loop.create_task(bkbot.renewPublicChannel())
        loop.create_task(bkbot.cleanupPublicChannel())
    elif bkbot.args.resumechannelupdate:
        loop.create_task(bkbot.resumePublicChannelUpdate())
        loop.create_task(bkbot.cleanupPublicChannel())
    elif bkbot.args.forcebatchprocess:
        loop.create_task(bkbot.batchProcess())
    elif bkbot.args.nukechannel:
        loop.create_task(nukeChannel(bkbot))
    elif bkbot.args.cleanupchannel:
        loop.create_task(cleanupChannel(bkbot))
    elif bkbot.args.migrate:
        bkbot.crawler.migrateDBs()
    if bkbot.args.usernotify:
        loop.create_task(bkbot.notifyUsers())
    loop.create_task(runDaily(0, 1, bkbot.batchProcess()))
    bkbot.startBot()


if __name__ == '__main__':
    main()
