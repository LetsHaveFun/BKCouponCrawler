import logging
import os
from datetime import datetime
from enum import Enum
from io import BytesIO
from typing import Union, List, Optional

from barcode.ean import EuropeanArticleNumber13
from barcode.writer import ImageWriter
from couchdb.mapping import TextField, FloatField, ListField, IntegerField, BooleanField, Document, DictField, Mapping, \
    DateTimeField
from pydantic import BaseModel

from BotUtils import getImageBasePath
from Helper import getTimezone, getCurrentDate, getFilenameFromURL, SYMBOLS, normalizeString, formatDateGerman, couponTitleContainsFriesAndDrink, BotAllowedCouponTypes, \
    CouponType, \
    formatPrice, couponTitleContainsVeggieFood, shortenProductNames, couponTitleContainsPlantBasedFood


class CouponFilter(BaseModel):
    """ removeDuplicates: Enable to filter duplicated coupons for same products - only returns cheapest of all
     If the same product is available as paper- and app coupon, App coupon is preferred."""
    activeOnly: Optional[bool] = True
    isNotYetActive: Optional[Union[bool, None]] = None
    containsFriesAndCoke: Optional[Union[bool, None]] = None
    removeDuplicates: Optional[
        bool] = False  # Enable to filter duplicated coupons for same products - only returns cheapest of all
    allowedCouponTypes: Optional[Union[List[int], None]] = None  # None = allow all sources!
    isNew: Optional[Union[bool, None]] = None
    isHidden: Optional[Union[bool, None]] = None
    isVeggie: Optional[Union[bool, None]] = None
    isPlantBased: Optional[Union[bool, None]] = None
    isEatable: Optional[Union[bool, None]] = None
    sortCode: Optional[Union[None, int]]

class CouponTextRepresentationPLUMode(Enum):
    """ This can be used to define how PLUs in short texts shall be represented. """
    SHORT_PLU = 1
    LONG_PLU = 2
    ALL_PLUS = 3


class CouponSortMode:

    def __init__(self, text: str, isDescending: bool = False):
        self.text = text
        self.isDescending = isDescending

    def getSortCode(self) -> Union[int, None]:
        """ Returns position of current sort mode in array of all sort modes. """
        sortModes = getAllSortModes()
        index = 0
        for sortMode in sortModes:
            if sortMode == self:
                return index
            index += 1
        # This should never happen
        return None


class CouponSortModes:
    PRICE = CouponSortMode("Preis " + SYMBOLS.ARROW_UP)
    PRICE_DESCENDING = CouponSortMode("Preis " + SYMBOLS.ARROW_DOWN, isDescending=True)
    DISCOUNT = CouponSortMode("Rabatt " + SYMBOLS.ARROW_UP)
    DISCOUNT_DESCENDING = CouponSortMode("Rabatt " + SYMBOLS.ARROW_DOWN, isDescending=True)
    NEW = CouponSortMode("Neue Coupons " + SYMBOLS.ARROW_UP)
    NEW_DESCENDING = CouponSortMode("Neue Coupons " + SYMBOLS.ARROW_DOWN, isDescending=True)
    MENU_PRICE = CouponSortMode("Menü_Preis")
    TYPE_MENU_PRICE = CouponSortMode("Typ_Menü_Preis")


def getAllSortModes() -> list:
    # Important! The order of this will also determine the sort order which gets presented to the user!
    res = []
    for obj in CouponSortModes.__dict__.values():
        if isinstance(obj, CouponSortMode):
            res.append(obj)
    return res


def getNextSortMode(currentSortMode: CouponSortMode) -> CouponSortMode:
    allSortModes = getAllSortModes()
    if currentSortMode is None:
        return allSortModes[0]
    for index in range(len(allSortModes)):
        sortMode = allSortModes[index]
        if sortMode == currentSortMode:
            if index == (len(allSortModes) - 1):
                # Last sortMode in list --> Return first
                return allSortModes[0]
            else:
                # Return next sortMode
                return allSortModes[index + 1]
    # Fallback, should not be needed
    return currentSortMode


def getSortModeBySortCode(sortCode: int) -> CouponSortMode:
    allSortModes = getAllSortModes()
    if sortCode < len(allSortModes):
        return allSortModes[sortCode]
    else:
        # Fallback
        return allSortModes[0]


class CouponView:

    def getFilter(self) -> CouponFilter:
        return self.couponfilter

    def __init__(self, couponfilter: CouponFilter, includeVeggieSymbol: Union[bool, None] = None, highlightFavorites: Union[bool, None] = None, allowModifyFilter: bool = True,
                 title: str = None):
        self.title = title
        self.couponfilter = couponfilter
        self.includeVeggieSymbol = includeVeggieSymbol
        self.highlightFavorites = highlightFavorites
        self.allowModifyFilter = allowModifyFilter

    def getViewCode(self) -> Union[int, None]:
        """ Returns position of current sort mode in array of all sort modes. """
        couponViews = getAllCouponViews()
        index = 0
        for couponView in couponViews:
            if couponView == self:
                return index
            index += 1
        # This should never happen
        return None


class CouponViews:
    ALL = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.MENU_PRICE.getSortCode(), isEatable=True), title="Alle Coupons")
    ALL_WITHOUT_MENU = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), containsFriesAndCoke=False, isEatable=True), title="Alle Coupons ohne Menü")
    ALL_WITH_MENU = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), containsFriesAndCoke=True, isEatable=True), title="Alle Coupons mit Menü")
    CATEGORY = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.MENU_PRICE.getSortCode()))
    CATEGORY_WITHOUT_MENU = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.MENU_PRICE.getSortCode(), containsFriesAndCoke=False))
    HIDDEN_APP_COUPONS_ONLY = CouponView(
        couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), allowedCouponTypes=[CouponType.APP], isHidden=True), title="App Coupons versteckte")
    VEGGIE = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), isVeggie=True, isEatable=True), includeVeggieSymbol=False,
                        title=f"{SYMBOLS.BROCCOLI}Veggie Coupons{SYMBOLS.BROCCOLI}")
    MEAT_WITHOUT_PLANT_BASED = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), isPlantBased=False, isEatable=True), title="Fleisch ohne Plant Based Coupons")
    # Dummy item basically only used for holding default sortCode for users' favorites
    FAVORITES = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode()), highlightFavorites=False, allowModifyFilter=False,
                           title=f"{SYMBOLS.STAR}Favoriten{SYMBOLS.STAR}")


def getAllCouponViews() -> List[CouponView]:
    res = []
    for obj in CouponViews.__dict__.values():
        if isinstance(obj, CouponView):
            res.append(obj)
    return res


def getCouponViewByIndex(index: int) -> Union[CouponView, None]:
    allCouponViews = getAllCouponViews()
    if index < len(allCouponViews):
        return allCouponViews[index]
    else:
        # Fallback
        return allCouponViews[0]


COUPON_IS_NEW_FOR_SECONDS = 24 * 60 * 60


class Coupon(Document):
    plu = TextField()
    uniqueID = TextField()
    price = IntegerField()
    priceCompare = IntegerField()
    staticReducedPercent = IntegerField()
    title = TextField()
    subtitle = TextField()
    timestampAddedToDB = FloatField(default=0)
    timestampLastModifiedDB = FloatField(default=0)
    timestampStart = FloatField(default=0)
    timestampExpireInternal = FloatField()  # Internal expire-date
    timestampExpire = FloatField()  # Expire date used by BK in their apps -> "Real" expire date.
    timestampCouponNotInAPIAnymore = FloatField() # 2023-05-09: Not used at this moment
    timestampIsNew = FloatField(default=0)  # Last timestamp from which on this coupon was new
    dateFormattedExpire = TextField()
    imageURL = TextField()
    paybackMultiplicator = IntegerField()
    productIDs = ListField(IntegerField())
    type = IntegerField(name='source')  # Legacy. This is called "type" now!
    isNewUntilDate = TextField()  # Date until which this coupon shall be treated as new. Use this as an override of default handling.
    isHidden = BooleanField(default=False)  # Typically only available for upsell App coupons
    description = TextField()
    # TODO: Make use of this once it is possible for users to add coupons to DB via API
    # addedVia = IntegerField()
    tags = ListField(TextField())
    webviewID = TextField()
    webviewURL = TextField()

    def __str__(self):
        return f'{self.id=} | {self.plu} | {self.getTitle()} | {self.getPriceFormatted()} | START: {self.getStartDateFormatted()} | END {self.getExpireDateFormatted()}  | WEBVIEW: {self.getWebviewURL()}'

    def forceDisplayQR(self) -> bool:
        if self.plu is None:
            # No readable PLU code -> QR code is needed to order this item.
            return True
        else:
            return False

    def getPLUOrUniqueIDOrRedemptionHint(self) -> str:
        """ Returns PLU if existant, returns UNIQUE_ID otherwise. """
        if self.plu is not None:
            return self.plu
        else:
            showQrHintWhenPLUIsUnavailable = True
            if showQrHintWhenPLUIsUnavailable:
                return 'QR! ' + self.id
            else:
                return self.id

    def getNormalizedTitle(self) -> Union[str, None]:
        return normalizeString(self.getTitle())

    def getTitle(self) -> Union[str, None]:
        if self.paybackMultiplicator is not None:
            return f'{self.paybackMultiplicator}Fach auf alle Speisen & Getränke'
        else:
            return self.title

    def getSubtitle(self) -> Union[str, None]:
        return self.subtitle

    def getTitleShortened(self, includeVeggieSymbol: bool) -> Union[str, None]:
        shortenedTitle = shortenProductNames(self.getTitle())
        if includeVeggieSymbol:
            nutritionSymbol = self.getNutritionSymbols()
            if nutritionSymbol is not None:
                shortenedTitle = nutritionSymbol + shortenedTitle
        return shortenedTitle

    def getNutritionSymbols(self) -> Union[str, None]:
        if not self.isEatable():
            return None
        enableMeatSymbol = False
        if enableMeatSymbol and self.containsMeat():
            return '🥩'
        elif self.isVeggie():
            return SYMBOLS.BROCCOLI
        else:
            return None

    def isExpiredForLongerTime(self) -> bool:
        """ Using this check, coupons that e.g. expire on midnight and get elongated will not be marked as new because really they aren't. """
        expireDatetime = self.getExpireDatetime()
        if expireDatetime is None:
            return True
        elif getCurrentDate().second - expireDatetime.second > 3600:
            """ 
             Coupon expired over one hour ago -> We consider this a "longer time"
             Using this check, coupons that e.g. expire on midnight and get elongated will not be marked as new because really they aren't.
             """
            return True
        else:
            """ Coupon is not expired or not "long enough". """
            return False

    def isExpired(self) -> bool:
        expireDatetime = self.getExpireDatetime()
        if expireDatetime is None or expireDatetime < getCurrentDate():
            # Coupon is expired
            return True
        else:
            return False

    def isNotYetActive(self) -> bool:
        startDatetime = self.getStartDatetime()
        if startDatetime is not None and startDatetime > getCurrentDate():
            # Start time hasn't been reached yet -> Coupon is not valid yet
            return True
        else:
            return False

    def isValid(self) -> bool:
        """ If this returns true, we can present the coupon to the user.
         If this returns false, this usually means that the coupon is expired or not yet available. """
        if self.isExpired() or self.isNotYetActive():
            return False
        else:
            return True

    def isContainsFriesAndDrink(self) -> bool:
        return couponTitleContainsFriesAndDrink(self.getTitle())

    def isPlantBased(self) -> bool:
        if self.tags is not None:
            # First check tags
            for tag in self.tags:
                tag = tag.lower()
                if 'plant' in tag:
                    return True
        if couponTitleContainsPlantBasedFood(self.getTitle()):
            return True
        else:
            return False

    def isVeggie(self) -> bool:
        if self.type == CouponType.PAYBACK:
            # Yes, Payback coupons are technically veggie except for those that are only valid for articles containing meat
            return True
        elif self.containsMeat():
            """ 
            Check if coupon contains meat. Some of them are wrongly tagged so ket's fix that by also looking into the product titles.
             """
            return False
        elif self.isPlantBased():
            return True
        elif couponTitleContainsVeggieFood(self.getTitle()):
            # No result? Fallback to other, more unsafe methods.
            return True
        else:
            # Last resort: Check if tags contain any useful information.
            if self.tags is not None:
                for tag in self.tags:
                    tag = tag.lower()
                    if tag == 'sweetkings':
                        return True
        # If in doubt, the product is not veggie
        return False

    def containsMeat(self) -> bool:
        """ Returns true if this coupon contains at least one article with meat. """
        """ First check for plant based stuff in title because BK sometimes has wrong tags (e.g. tag contains "chicken" when article is veggie lol)... """
        if self.isPlantBased():
            return False
        elif self.tags is not None:
            # Now check for meat in tags
            # More tags:
            # KingSnacks -> Can be meat
            # NoPreference -> Can be anything, most items got this tag only
            for tag in self.tags:
                tag = tag.lower()
                if 'beef' in tag or 'chicken' in tag:
                    return True

        titleLower = self.getTitle().lower()
        if 'chicken' in titleLower:
            return True
        else:
            return False

    def isSweet(self) -> bool:
        if self.tags is not None and len(self.tags) == 1 and self.tags[0].lower() == 'sweetkings':
            return True
        else:
            return False

    def getPrice(self) -> Union[float, None]:
        return self.price

    def getPriceCompare(self) -> Union[float, None]:
        """ Returns original price of this product (or all product it contains) without discount. """
        return self.priceCompare

    def isEatable(self) -> bool:
        """ If the product(s) this coupon provide(s) is/are not eatable and e.g. just probide a discount like Payback coupons, this will return False, else True. """
        if self.type == CouponType.PAYBACK:
            return False
        else:
            return True

    def isEligibleForDuplicateRemoval(self):
        """ Returns true if coupon title can be used to remove duplicates.
         """
        if self.type == CouponType.PAYBACK:
            return False
        else:
            return True

    def isNewCoupon(self) -> bool:
        """ Determines whether or not this coupon is considered 'new'. """
        currentTimestamp = getCurrentDate().timestamp()
        timePassedSinceCouponWasAddedToDB = currentTimestamp - self.timestampAddedToDB
        if timePassedSinceCouponWasAddedToDB < COUPON_IS_NEW_FOR_SECONDS:
            return True
        timePassedSinceLastNewTimestamp = currentTimestamp - self.timestampIsNew
        if timePassedSinceLastNewTimestamp < COUPON_IS_NEW_FOR_SECONDS:
            # Coupon has been added just recently and thus can still be considered 'new'
            # couponNewSecondsRemaining = COUPON_IS_NEW_FOR_SECONDS - timePassedSinceLastNewTimestamp
            # print(f'Coupon is considered as new for {formatSeconds(seconds=couponNewSecondsRemaining)} time')
            return True
        timePassedSinceCouponValidityStarted = -1
        if self.timestampStart > 0:
            timePassedSinceCouponValidityStarted = currentTimestamp - self.timestampStart
        if 0 < timePassedSinceCouponValidityStarted < COUPON_IS_NEW_FOR_SECONDS:
            return True
        if self.isNewUntilDate is not None:
            # Check if maybe coupon should be considered as new for X
            try:
                enforceIsNewOverrideUntilDate = datetime.strptime(self.isNewUntilDate + ' 23:59:59',
                                                                  '%Y-%m-%d %H:%M:%S').astimezone(getTimezone())
                if enforceIsNewOverrideUntilDate.timestamp() > getCurrentDate().timestamp():
                    return True
                else:
                    return False
            except:
                # This should never happen
                logging.warning("Coupon.isNewCoupon: WTF invalid date format??")
                return False
        return False

    def getStartDatetime(self) -> Union[datetime, None]:
        """ Returns datetime from which coupon is valid. Not all coupons got a startDatetime. """
        if self.timestampStart is not None and self.timestampStart > 0:
            return datetime.fromtimestamp(self.timestampStart, getTimezone())
        else:
            # Start date must not always be given
            return None

    def getExpireDatetime(self) -> datetime:
        return datetime.fromtimestamp(self.timestampExpire, getTimezone())

    def getExpireDateFormatted(self, fallback: Union[str, None] = None) -> Union[str, None]:
        if self.timestampExpire is not None:
            # return self.dateFormattedExpire
            return formatDateGerman(datetime.fromtimestamp(self.timestampExpire))
        else:
            return fallback

    def getStartDateFormatted(self, fallback: Union[str, None] = None) -> Union[str, None]:
        if self.timestampStart is not None:
            return formatDateGerman(datetime.fromtimestamp(self.timestampStart))
        else:
            return fallback

    def getPriceFormatted(self, fallback: Union[str, None] = None) -> Union[str, None]:
        if self.price is not None:
            return formatPrice(self.price)
        else:
            return fallback

    def getPriceCompareFormatted(self, fallback=None) -> Union[str, None]:
        priceCompare = self.getPriceCompare()
        if priceCompare is not None:
            return formatPrice(priceCompare)
        else:
            return fallback

    def getReducedPercentage(self) -> Union[float, None]:
        priceCompare = self.getPriceCompare()
        if self.paybackMultiplicator is not None:
            # 0.5 points per euro (= base discount of 0.5% without higher multiplicator)
            return 0.5 * self.paybackMultiplicator
        elif self.price is not None and priceCompare is not None:
            return (1 - (self.price / priceCompare)) * 100
        elif self.staticReducedPercent is not None:
            return self.staticReducedPercent
        else:
            return None

    def getReducedPercentageFormatted(self, fallback=None) -> Union[str, None]:
        """ Returns price reduction in percent if bothb the original price and the reduced/coupon-price are available.
         E.g. "-39%" """
        reducedPercentage = self.getReducedPercentage()
        if reducedPercentage is not None:
            if self.paybackMultiplicator is not None:
                # Add one decimal point for low percentage reducements such as Payback coupons as those will often only get us like 2.5% discount.
                return '-' + f'{reducedPercentage:2.1f}' + '%'
            else:
                return '-' + f'{reducedPercentage:2.0f}' + '%'
        else:
            return fallback

    def getAddedVia(self):
        """ Returns origin of how this coupon got added to DB e.g. API, by admin etc. """
        return self.addedVia

    def getCouponType(self):
        return self.type

    def getUniqueIdentifier(self) -> str:
        """ Returns an unique identifier String which can be used to compare coupon objects. """
        expiredateStr = self.getExpireDateFormatted(fallback='undefined')
        return self.id + '_' + (
            "undefined" if self.plu is None else self.plu) + '_' + expiredateStr + '_' + self.imageURL

    def getComparableValue(self) -> str:
        """ Returns value which can be used to compare given coupon object to another one.
         This might be useful in the future to e.g. find coupons that contain exactly the same products and cost the same price as others.
          Do NOT use this to compare multiple Coupon objects! Use couponDBGetUniqueIdentifier instead!
          """
        return self.getTitle().lower() + str(self.price)

    def getImagePath(self) -> str:
        if self.imageURL.startswith('file://'):
            # Image should be present in local storage: Use pre-given path
            return self.imageURL.replace('file://', '')
        else:
            return getImageBasePath() + "/" + self.id + "_" + getFilenameFromURL(self.imageURL)

    def getImagePathQR(self) -> str:
        return getImageBasePath() + "/" + self.id + "_QR.png"

    def getImageQR(self):
        path = self.getImagePathQR()
        if os.path.exists(path):
            return open(path, mode='rb')
        else:
            # Return fallback --> This should never happen!
            logging.warning(f'Returning fallback QR image for: {path}')
            return open('media/fallback_image_missing_qr_image.jpeg', mode='rb')

    def getWebviewURL(self) -> Union[str, None]:
        if self.webviewID is not None:
            # Default for DB coupons
            return f'https://www.burgerking.de/rewards/offers/{self.webviewID}'
        elif self.webviewURL is not None:
            # Static webview URL e.g. useful for Payback coupons -> Links to mydealz deals
            return self.webviewURL
        else:
            return None

    def generateCouponShortText(self, highlightIfNew: bool, includeVeggieSymbol: bool, plumode: CouponTextRepresentationPLUMode) -> str:
        """ Returns e.g. "Y15 | 2Whopper+M🍟+0,4Cola | 8,99€" """
        if plumode == CouponTextRepresentationPLUMode.ALL_PLUS and self.plu is not None:
            # All PLUs
            vouchercode = f"{self.plu} | {self.id}"
        elif plumode == CouponTextRepresentationPLUMode.SHORT_PLU and self.plu is not None:
            # Short-PLU
            vouchercode = self.plu
        else:
            # Long-PLU
            vouchercode = self.id
        couponText = ''
        if highlightIfNew and self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += vouchercode + " | " + self.getTitleShortened(includeVeggieSymbol=includeVeggieSymbol)
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponShortTextFormatted(self, highlightIfNew: bool) -> str:
        """ Returns e.g. "<b>Y15</b> | 2Whopper+M🍟+0,4Cola | 8,99€" """
        couponText = ''
        if highlightIfNew and self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += "<b>" + self.getPLUOrUniqueIDOrRedemptionHint() + "</b> | " + self.getTitleShortened(includeVeggieSymbol=True)
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponShortTextFormattedWithHyperlinkToChannelPost(self, highlightIfNew: bool, includeVeggieSymbol: bool, publicChannelName: str,
                                                                   messageID: int) -> str:
        """ Returns e.g. "Y15 | 2Whopper+M🍟+0,4Cola (https://t.me/betterkingpublic/1054) | 8,99€" """
        couponText = "<b>" + self.getPLUOrUniqueIDOrRedemptionHint() + "</b> | <a href=\"https://t.me/" + publicChannelName + '/' + str(
            messageID) + "\">"
        if highlightIfNew and self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += self.getTitleShortened(includeVeggieSymbol=includeVeggieSymbol) + "</a>"
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponLongTextFormatted(self) -> str:
        """ Returns e.g. "2 Whopper + Mittlere Pommes + 0,4L Cola
         <b>Y15</b> | 8,99€ | -25% " """
        couponText = ''
        if self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += self.getTitle()
        couponText += "\n<b>" + self.getPLUOrUniqueIDOrRedemptionHint() + "</b>"
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponLongTextFormattedWithHyperlinkToChannelPost(self, publicChannelName: str, messageID: int) -> str:
        """ Returns e.g. "2 Whopper + Mittlere Pommes +0,4L Cola (https://t.me/betterkingpublic/1054)
         <b>Y15</b> | 8,99€ | -25% " """
        couponText = "<a href=\"https://t.me/" + publicChannelName + '/' + str(
            messageID) + "\">"
        if self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += self.getTitle()
        couponText += "</a>"
        couponText += "\n<b>" + self.getPLUOrUniqueIDOrRedemptionHint() + "</b>"
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponLongTextFormattedWithDescription(self, highlightIfNew: bool):
        """
        :param highlightIfNew: Add emoji to text if coupon is new.
        :return: E.g. "<b>B3</b> | 1234 | 13.99€ | -50%\nGültig bis:19.06.2021\nCoupon.description"
        """
        couponText = ''
        if highlightIfNew and self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += self.getTitle() + '\n'
        # Add PLU information
        if self.plu is not None and self.plu != self.id:
            couponText += '<b>' + self.plu + '</b>' + ' | ' + self.id
        else:
            # No PLU available or PLU equals ID (This is e.g. the case for Payback coupons)
            couponText += '<b>' + self.id + '</b>'
        couponText = self.appendPriceInfoText(couponText)
        """ Expire date should be always given but we can't be 100% sure! """
        expireDateFormatted = self.getExpireDateFormatted()
        if expireDateFormatted is not None:
            couponText += '\nGültig bis ' + expireDateFormatted
        if self.description is not None:
            couponText += "\n" + self.description
        webviewURL = self.getWebviewURL()
        if self.plu is None:
            couponText += f'\n{SYMBOLS.WARNING} Keine nennbare PLU verfügbar -> QR Code zeigen!'
        if webviewURL is not None:
            couponText += f"\n{SYMBOLS.ARROW_RIGHT}<a href=\"{webviewURL}\">Webansicht</a>"
        return couponText

    def appendPriceInfoText(self, couponText: str) -> str:
        priceFormatted = self.getPriceFormatted()
        if priceFormatted is not None:
            couponText += " | " + priceFormatted
        reducedPercentage = self.getReducedPercentageFormatted()
        if reducedPercentage is not None:
            couponText += " | " + reducedPercentage
        return couponText

    def getPriceInfoText(self) -> Union[str, None]:
        priceInfoText = None
        priceFormatted = self.getPriceFormatted()
        if priceFormatted is not None:
            priceInfoText = priceFormatted
        reducedPercentage = self.getReducedPercentageFormatted()
        if reducedPercentage is not None:
            if priceInfoText is None:
                priceInfoText = reducedPercentage
            else:
                priceInfoText += " | " + reducedPercentage
        return priceInfoText


class UserFavoritesInfo:
    """ Helper class for users favorites. """

    def __init__(self, favoritesAvailable: Union[List[Coupon], None] = None,
                 favoritesUnavailable: Union[List[Coupon], None] = None):
        # Do not allow null values when arrays are expected. This makes it easier to work with this.
        if favoritesAvailable is None:
            favoritesAvailable = []
        if favoritesUnavailable is None:
            favoritesUnavailable = []
        self.couponsAvailable = favoritesAvailable
        self.couponsUnavailable = favoritesUnavailable

    def getUnavailableFavoritesText(self) -> Union[str, None]:
        if len(self.couponsUnavailable) == 0:
            return None
        else:
            unavailableFavoritesText = ''
            for coupon in self.couponsUnavailable:
                if len(unavailableFavoritesText) > 0:
                    unavailableFavoritesText += '\n'
                unavailableFavoritesText += coupon.id + ' | ' + coupon.getTitleShortened(includeVeggieSymbol=False)
                priceInfoText = coupon.getPriceInfoText()
                if priceInfoText is not None:
                    unavailableFavoritesText += ' | ' + priceInfoText
            return unavailableFavoritesText


MAX_SECONDS_WITHOUT_USAGE_UNTIL_AUTO_ACCOUNT_DELETION = 6 * 30 * 24 * 60 * 60
# X time before account would get deleted, we can inform the user X time before about upcoming auto account deletion
MAX_SECONDS_WITHOUT_USAGE_UNTIL_SEND_WARNING_TO_USER = MAX_SECONDS_WITHOUT_USAGE_UNTIL_AUTO_ACCOUNT_DELETION - 9 * 24 * 60 * 60
MAX_HOURS_ACTIVITY_TRACKING = 48
MAX_TIMES_INFORM_ABOUT_UPCOMING_AUTO_ACCOUNT_DELETION = 3
MIN_SECONDS_BETWEEN_UPCOMING_AUTO_DELETION_WARNING = 2 * 24 * 60 * 60


class User(Document):
    settings = DictField(
        Mapping.build(
            displayCouponCategoryAllCouponsLongListWithLongTitles=BooleanField(default=False),
            displayCouponCategoryAppCouponsHidden=BooleanField(default=True),
            # displayCouponCategoryMeatWithoutPlantBased=BooleanField(default=False),
            displayCouponCategoryVeggie=BooleanField(default=True),
            displayCouponCategoryPayback=BooleanField(default=True),
            displayCouponSortButton=BooleanField(default=True),
            enableTerminalMode=BooleanField(default=False),
            displayOffersButton=BooleanField(default=True),
            displayBKWebsiteURLs=BooleanField(default=True),
            displayFeedbackCodeGenerator=BooleanField(default=True),
            displayFAQLinkButton=BooleanField(default=True),
            displayDonateButton=BooleanField(default=True),
            displayAdminButtons=BooleanField(default=True),
            displayPlantBasedCouponsWithinGenericCategories=BooleanField(default=True),
            displayHiddenUpsellingAppCouponsWithinGenericCategories=BooleanField(default=True),
            hideDuplicates=BooleanField(default=False),
            notifyWhenFavoritesAreBack=BooleanField(default=False),
            notifyWhenNewCouponsAreAvailable=BooleanField(default=False),
            notifyMeAsAdminIfThereAreProblems=BooleanField(default=True),
            notifyOnBotNewsletter=BooleanField(default=True),
            highlightFavoriteCouponsInButtonTexts=BooleanField(default=True),
            highlightNewCouponsInCouponButtonTexts=BooleanField(default=True),
            highlightVeggieCouponsInCouponButtonTexts=BooleanField(default=True),
            displayQR=BooleanField(default=True),
            autoDeleteExpiredFavorites=BooleanField(default=False),
            enableBetaFeatures=BooleanField(default=False),
        )
    )
    botBlockedCounter = IntegerField(default=0)
    easterEggCounter = IntegerField(default=0)
    favoriteCoupons = DictField(default={})
    paybackCard = DictField(
        Mapping.build(
            paybackCardNumber=TextField(),
            addedDate=DateTimeField()
        ))
    couponViewSortModes = DictField(default={})
    pendingNotifications = ListField(TextField())
    # Rough timestamp when user user start commenad of bot last time -> Can be used to delete inactive users after X time
    timestampLastTimeBotUsed = FloatField(default=0)
    timestampLastTimeNotificationSentSuccessfully = FloatField(default=0)
    timesInformedAboutUpcomingAutoAccountDeletion = IntegerField(default=0)
    timestampLastTimeWarnedAboutUpcomingAutoAccountDeletion = IntegerField(default=0)
    timestampLastTimeBlockedBot = IntegerField(default=0)

    def hasProbablyBlockedBot(self) -> bool:
        if self.botBlockedCounter > 0:
            return True
        else:
            return False

    def hasProbablyBlockedBotForLongerTime(self) -> bool:
        if self.botBlockedCounter >= 30:
            return True
        else:
            return False

    def isEligableForAutoDeletion(self):
        """ If this returns True, upper handling is allowed to delete this account as it looks like it has been abandoned by the user. """
        if self.hasProbablyBlockedBotForLongerTime():
            return True
        elif self.getSecondsUntilAccountDeletion() == 0 and self.timesInformedAboutUpcomingAutoAccountDeletion >= MAX_TIMES_INFORM_ABOUT_UPCOMING_AUTO_ACCOUNT_DELETION:
            # Looks like user hasn't used this bot for a loong time. Only allow this to return true if user has been warned enough times in beforehand.
            return True
        else:
            return False

    def hasDefaultSettings(self) -> bool:

        for settingKey, settingValue in self["settings"].items():
            settingInfo = USER_SETTINGS_ON_OFF.get(settingKey)
            if settingInfo is None:
                # Ignore keys that aren't covered in our settings map
                continue
            elif settingValue != settingInfo['default']:
                return False
        # Check for custom sort modes
        if self.hasStoredSortModes():
            # User has used/saved custom sort modes
            return False
        # No non-default value found -> User has default settings
        return True

    def hasStoredSortModes(self) -> bool:
        if self.couponViewSortModes is not None and len(self.couponViewSortModes) > 0:
            # User has saved preferred sort modes
            return True
        else:
            # User does not have any stored sort modes
            return False

    def hasFoundEasterEgg(self) -> bool:
        if self.easterEggCounter > 0:
            return True
        else:
            return False

    def isFavoriteCoupon(self, coupon: Coupon):
        """ Checks if given coupon is users' favorite """
        return self.isFavoriteCouponID(coupon.id)

    def isFavoriteCouponID(self, couponID: str):
        if couponID in self.favoriteCoupons:
            return True
        else:
            return False

    def addFavoriteCoupon(self, coupon: Coupon):
        self.favoriteCoupons[coupon.id] = coupon._data

    def deleteFavoriteCoupon(self, coupon: Coupon):
        self.deleteFavoriteCouponID(coupon.id)

    def deleteFavoriteCouponID(self, couponID: str):
        del self.favoriteCoupons[couponID]

    def isAllowSendFavoritesNotification(self):
        if self.settings.autoDeleteExpiredFavorites:
            # User wants expired coupons to be auto-deleted so it is impossible to inform him about expired favourites that are back.
            return False
        elif self.settings.notifyWhenFavoritesAreBack:
            # User wants to be informed about expired favourite coupons that are back.
            return True
        else:
            # User does not want to be informed about expired favourite coupons that are back.
            return False

    def getPaybackCardNumber(self) -> Union[str, None]:
        """ Returns Payback card number of users' [first] Payback card. """
        """ Can this be considered a workaround or is the mapping made in a stupid way that it does not return "None" for keys without defined defaults??!
          doing User.paybackCard.paybackCardNumber directly would raise an AttributeError!
          Alternative would be to set empty String as default value. """
        if len(self.paybackCard) > 0:
            return self.paybackCard.paybackCardNumber
        else:
            return None

    def getPaybackCardImage(self) -> bytes:
        ean = EuropeanArticleNumber13(ean='240' + self.getPaybackCardNumber(), writer=ImageWriter())
        file = BytesIO()
        ean.write(file, options={'foreground': 'black'})
        return file.getvalue()

    def addPaybackCard(self, paybackCardNumber: str):
        if self.paybackCard is None or len(self.paybackCard) == 0:
            """ Workaround for Document bug/misbehavior. """
            self['paybackCard'] = {}
        self.paybackCard.paybackCardNumber = paybackCardNumber
        self.paybackCard.addedDate = datetime.now()

    def deletePaybackCard(self):
        """ Deletes users' [first] Payback card. """
        dummyUser = User()
        self.paybackCard = dummyUser.paybackCard

    def getUserFavoritesInfo(self, couponsFromDB: dict, returnSortedCoupons: bool) -> UserFavoritesInfo:
        """
        Gathers information about the given users' favorite available/unavailable coupons.
        Coupons from DB are required to get current dataset of available favorites.
        """
        if len(self.favoriteCoupons) == 0:
            # User does not have any favorites set --> There is no point to look for the additional information
            return UserFavoritesInfo()
        availableFavoriteCoupons = []
        unavailableFavoriteCoupons = []
        for uniqueCouponID, coupon in self.favoriteCoupons.items():
            couponFromProductiveDB = couponsFromDB.get(uniqueCouponID)
            if couponFromProductiveDB is not None and couponFromProductiveDB.isValid():
                availableFavoriteCoupons.append(couponFromProductiveDB)
            else:
                # User chosen favorite coupon has expired or is not in DB
                coupon = Coupon.wrap(coupon)  # We want a 'real' coupon object
                unavailableFavoriteCoupons.append(coupon)
        # Sort all coupon arrays by price
        if self.settings.hideDuplicates:
            availableFavoriteCoupons = removeDuplicatedCoupons(availableFavoriteCoupons)
        if returnSortedCoupons:
            favoritesFilter = CouponViews.FAVORITES.getFilter()
            availableFavoriteCoupons = sortCouponsAsList(availableFavoriteCoupons, favoritesFilter.sortCode)
            unavailableFavoriteCoupons = sortCouponsAsList(unavailableFavoriteCoupons, favoritesFilter.sortCode)
        return UserFavoritesInfo(favoritesAvailable=availableFavoriteCoupons,
                                 favoritesUnavailable=unavailableFavoriteCoupons)

    def getSortModeForCouponView(self, couponView: CouponView) -> CouponSortMode:
        if self.couponViewSortModes is not None:
            # User has at least one custom sortCode for one CouponView.
            sortCode = self.couponViewSortModes.get(str(couponView.getViewCode()))
            if sortCode is not None:
                # User has saved SortMode for this CouponView.
                return getSortModeBySortCode(sortCode=sortCode)
            else:
                # User does not have saved SortMode for this CouponView --> Return default
                return getSortModeBySortCode(sortCode=couponView.couponfilter.sortCode)
        else:
            # User has no saved sortCode --> Return default
            return getSortModeBySortCode(sortCode=couponView.couponfilter.sortCode)

    def getNextSortModeForCouponView(self, couponView: CouponView) -> CouponSortMode:
        currentSortMode = self.getSortModeForCouponView(couponView=couponView)
        return getNextSortMode(currentSortMode=currentSortMode)

    def setCustomSortModeForCouponView(self, couponView: CouponView, sortMode: CouponSortMode):
        if self.couponViewSortModes is None or len(self.couponViewSortModes) == 0:
            """ Workaround for stupid Document bug/misbehavior. """
            self["couponViewSortModes"] = {}
            # self.couponViewSortModes = {} --> This does not work
        self.couponViewSortModes[str(couponView.getViewCode())] = sortMode.getSortCode()

    def hasRecentlyUsedBot(self) -> bool:
        if self.timestampLastTimeBotUsed == 0:
            # User has never used bot - this is nearly impossible unless user has been manually added to DB.
            return False
        else:
            currentTimestamp = getCurrentDate().timestamp()
            if currentTimestamp - self.timestampLastTimeBotUsed < MAX_HOURS_ACTIVITY_TRACKING * 60 * 60:
                return True
            else:
                return False

    def hasEverUsedBot(self) -> bool:
        """ Every user in DB should have used the bot at least once so this is kind of an ugly helper function which will return False
         if DB values do not match current DB activity values e.g. due to DB changes.
          Can especially be used to avoid sending account deletion notifications to users who are not eligable for auto account deletion. """
        if self.timestampLastTimeBotUsed > 0:
            return True
        elif self.timestampLastTimeNotificationSentSuccessfully > 0:
            return True
        elif len(self.favoriteCoupons) > 0:
            return True
        elif self.getPaybackCardNumber() is not None:
            return True
        else:
            return False

    def updateActivityTimestamp(self, force: bool = False) -> bool:
        if force or not self.hasRecentlyUsedBot():
            self.timestampLastTimeBotUsed = getCurrentDate().timestamp()
            # Reset this as user is active and is not about to be auto deleted
            self.timesInformedAboutUpcomingAutoAccountDeletion = 0
            # Reset this because user is using bot so it's obviously not blocked (anymore)
            self.botBlockedCounter = 0
            return True
        else:
            return False

    def hasRecentlyReceivedBotNotification(self) -> bool:
        if self.timestampLastTimeNotificationSentSuccessfully == 0:
            # User has never received notification from bot.
            return False
        else:
            currentTimestamp = getCurrentDate().timestamp()
            if currentTimestamp - self.timestampLastTimeNotificationSentSuccessfully < MAX_HOURS_ACTIVITY_TRACKING * 60 * 60:
                return True
            else:
                return False

    def updateNotificationReceivedActivityTimestamp(self, force: bool = False) -> bool:
        if force or not self.hasRecentlyReceivedBotNotification():
            self.timestampLastTimeNotificationSentSuccessfully = getCurrentDate().timestamp()
            # Reset this as user is active and is not about to be auto deleted
            self.timesInformedAboutUpcomingAutoAccountDeletion = 0
            # Reset this because user is using bot so it's obviously not blocked (anymore)
            self.botBlockedCounter = 0
            return True
        else:
            return False

    def getSecondsUntilAccountDeletion(self) -> float:
        secondsPassedSinceLastAccountActivity = self.getSecondsPassedSinceLastAccountActivity()
        if secondsPassedSinceLastAccountActivity > MAX_SECONDS_WITHOUT_USAGE_UNTIL_AUTO_ACCOUNT_DELETION:
            # Account can be deleted now
            return 0
        else:
            # Account can be deleted in X seconds
            return MAX_SECONDS_WITHOUT_USAGE_UNTIL_AUTO_ACCOUNT_DELETION - secondsPassedSinceLastAccountActivity

    def getSecondsPassedSinceLastAccountActivity(self) -> float:
        """ Returns smaller of these two values:
         - Seconds passed since user used bot last time
         - Seconds passed since bot sent user notification successfully last time
         """
        secondsPassedSinceLastUsage = self.getSecondsPassedSinceLastTimeUsed()
        secondsPassedSinceLastNotificationSentSuccessfully = self.getSecondsPassedSinceLastTimeNotificationSentSuccessfully()
        return min(secondsPassedSinceLastUsage, secondsPassedSinceLastNotificationSentSuccessfully)

    def getSecondsPassedSinceLastTimeUsed(self) -> float:
        return getCurrentDate().timestamp() - self.timestampLastTimeBotUsed

    def getSecondsPassedSinceLastTimeNotificationSentSuccessfully(self) -> float:
        return getCurrentDate().timestamp() - self.timestampLastTimeNotificationSentSuccessfully

    def allowWarningAboutUpcomingAutoAccountDeletion(self) -> bool:
        currentTimestampSeconds = getCurrentDate().timestamp()
        if currentTimestampSeconds + MAX_SECONDS_WITHOUT_USAGE_UNTIL_AUTO_ACCOUNT_DELETION - self.timestampLastTimeBotUsed <= MAX_SECONDS_WITHOUT_USAGE_UNTIL_SEND_WARNING_TO_USER and currentTimestampSeconds - self.timestampLastTimeWarnedAboutUpcomingAutoAccountDeletion > MIN_SECONDS_BETWEEN_UPCOMING_AUTO_DELETION_WARNING and self.timesInformedAboutUpcomingAutoAccountDeletion < MAX_TIMES_INFORM_ABOUT_UPCOMING_AUTO_ACCOUNT_DELETION:
            return True
        else:
            return False

    def resetSettings(self):
        dummyUser = User()
        self.settings = dummyUser.settings
        self.couponViewSortModes = {}


class InfoEntry(Document):
    dateLastSuccessfulChannelUpdate = DateTimeField()
    dateLastSuccessfulCrawlRun = DateTimeField()
    informationMessageID = TextField()
    couponTypeOverviewMessageIDs = DictField(default={})
    messageIDsToDelete = ListField(IntegerField(), default=[])
    lastMaintenanceModeState = BooleanField()

    def addMessageIDToDelete(self, messageID: int) -> bool:
        # Avoid duplicates
        if messageID not in self.messageIDsToDelete:
            self.messageIDsToDelete.append(messageID)
            return True
        else:
            return False

    def addMessageIDsToDelete(self, messageIDs: List) -> bool:
        containsAtLeastOneNewID = False
        for messageID in messageIDs:
            if self.addMessageIDToDelete(messageID):
                containsAtLeastOneNewID = True
        return containsAtLeastOneNewID

    def addCouponCategoryMessageID(self, couponType: int, messageID: int):
        self.couponTypeOverviewMessageIDs.setdefault(couponType, []).append(messageID)

    def getMessageIDsForCouponCategory(self, couponType: int) -> List[int]:
        return self.couponTypeOverviewMessageIDs.get(str(couponType), [])

    def getAllCouponCategoryMessageIDs(self) -> List[int]:
        messageIDs = []
        for messageIDsTemp in self.couponTypeOverviewMessageIDs.values():
            messageIDs += messageIDsTemp
        return messageIDs

    def deleteCouponCategoryMessageIDs(self, couponType: int):
        if str(couponType) in self.couponTypeOverviewMessageIDs:
            del self.couponTypeOverviewMessageIDs[str(couponType)]

    def deleteAllCouponCategoryMessageIDs(self):
        self.couponTypeOverviewMessageIDs = {}


class ChannelCoupon(Document):
    """ Represents a coupon posted in a Telegram channel.
     Only contains minimum of required information as information about coupons itself is stored in another DB. """
    uniqueIdentifier = TextField()
    channelMessageID_image_and_qr_date_posted = DateTimeField()
    channelMessageID_image = IntegerField()
    channelMessageID_qr = IntegerField()
    channelMessageID_text = IntegerField()
    channelMessageID_text_date_posted = DateTimeField()

    def getMessageIDs(self) -> List[int]:
        messageIDs = []
        if self.channelMessageID_image is not None:
            messageIDs.append(self.channelMessageID_image)
        if self.channelMessageID_qr is not None:
            messageIDs.append(self.channelMessageID_qr)
        if self.channelMessageID_text is not None:
            messageIDs.append(self.channelMessageID_text)
        return messageIDs

    def deleteMessageIDs(self):
        # Nullification
        self.channelMessageID_image = None
        self.channelMessageID_qr = None
        self.channelMessageID_text = None

    def getMessageIDForChatHyperlink(self) -> Union[None, int]:
        return self.channelMessageID_image


def getCouponsTotalPrice(coupons: List[Coupon]) -> float:
    """ Returns the total summed price of a list of coupons. """
    totalSum = 0
    for coupon in coupons:
        if coupon.price is not None:
            totalSum += coupon.price
    return totalSum


def getCouponsSeparatedByType(coupons: dict) -> dict:
    """ Returns dict containing lists of coupons by type """
    couponsSeparatedByType = {}
    for couponType in BotAllowedCouponTypes:
        couponsTmp = list(filter(lambda x: x[Coupon.type.name] == couponType, list(coupons.values())))
        if couponsTmp is not None and len(couponsTmp) > 0:
            couponsSeparatedByType[couponType] = couponsTmp
    return couponsSeparatedByType


def sortCouponsByPrice(couponList: List[Coupon], descending: bool = False) -> List[Coupon]:
    """Sort by price -> But price is not always given -> Place items without prices at the BEGINNING of each list."""
    if isinstance(couponList, dict):
        couponList = couponList.values()
    return sorted(couponList,
                  key=lambda x: -1 if x.getPrice() is None else x.getPrice(), reverse=descending)


def sortCouponsByDiscount(couponList: List[Coupon], descending: bool = False) -> List[Coupon]:
    """Sort by price -> But price is not always given -> Place items without prices at the BEGINNING of each list."""
    if isinstance(couponList, dict):
        couponList = couponList.values()
    return sorted(couponList,
                  key=lambda x: 0 if x.getReducedPercentage() is None else x.getReducedPercentage(), reverse=descending)


def sortCouponsByNew(couponList: List[Coupon], descending: bool = False) -> List[Coupon]:
    """Sort by price -> But price is not always given -> Place items without prices at the BEGINNING of each list."""
    if isinstance(couponList, dict):
        couponList = couponList.values()
    return sorted(couponList,
                  key=lambda x: x.isNewCoupon(), reverse=descending)


def getCouponTitleMapping(coupons: Union[dict, list]) -> dict:
    """ Maps normalized coupon titles to coupons with the goal of being able to match coupons by title
    e.g. to find duplicates or coupons with different IDs containing the same products. """
    if isinstance(coupons, dict):
        coupons = coupons.values()
    couponTitleMappingTmp = {}
    for coupon in coupons:
        couponTitleMappingTmp.setdefault(coupon.getNormalizedTitle(), []).append(coupon)
    return couponTitleMappingTmp


class SettingCategory:

    def __init__(self, title: str):
        self.title = title

    def getViewCode(self) -> Union[int, None]:
        """ Returns position of current sort mode in array of all sort modes. """
        couponViews = getAllCouponViews()
        index = 0
        for couponView in couponViews:
            if couponView == self:
                return index
            index += 1
        # This should never happen
        return None


class SettingCategories:
    MAIN_MENU = SettingCategory(title='Hauptmenü Buttons')
    GLOBAL_FILTERS = SettingCategory(title='Globale Coupon Filter')
    COUPON_DISPLAY = SettingCategory(title='Anzeigeeinstellungen')
    NOTIFICATIONS = SettingCategory(title='Benachrichtigungen')
    MISC = SettingCategory(title='Sonstige')


USER_SETTINGS_ON_OFF = {
    # TODO: Obtain these Keys and default values from "User" Mapping class and remove this mess!
    "displayCouponCategoryAllCouponsLongListWithLongTitles": {
        "category": SettingCategories.MAIN_MENU,
        "description": f"Kategorie 'Alle Coupons Liste lange Titel + Pics' zeigen",
        "default": False
    },
    "displayCouponCategoryAppCouponsHidden": {
        "category": SettingCategories.MAIN_MENU,
        "description": f"Kategorie 'App Coupons versteckte' zeigen",
        "default": True
    },
    # "displayCouponCategoryMeatWithoutPlantBased": {
    #     "category": SettingCategories.MAIN_MENU,
    #     "description": f"Kategorie Coupons ohne PlantBased ({SYMBOLS.MEAT}) zeigen",
    #     "default": False
    # },
    "displayCouponCategoryVeggie": {
        "category": SettingCategories.MAIN_MENU,
        "description": f"Kategorie Veggie Coupons ({SYMBOLS.BROCCOLI}) zeigen",
        "default": True
    },
    "displayCouponCategoryPayback": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Kategorie Payback Buttons zeigen",
        "default": True
    },
    "displayOffersButton": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Angebote Button zeigen",
        "default": True
    },
    "displayBKWebsiteURLs": {
        "category": SettingCategories.MAIN_MENU,
        "description": "BK Verlinkungen Buttons zeigen",
        "default": True
    },
    "displayFeedbackCodeGenerator": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Feedback Code Generator Button zeigen",
        "default": True
    },
    "displayFAQLinkButton": {
        "category": SettingCategories.MAIN_MENU,
        "description": "FAQ Button zeigen",
        "default": True
    },
    "displayDonateButton": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Spenden Button zeigen",
        "default": True
    },
    "displayAdminButtons": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Admin Buttons anzeigen",
        "default": True
    },
    "displayPlantBasedCouponsWithinGenericCategories": {
        "category": SettingCategories.GLOBAL_FILTERS,
        "description": "Plant Based Coupons in Kategorien zeigen",
        "default": True
    },
    "displayHiddenUpsellingAppCouponsWithinGenericCategories": {
        "category": SettingCategories.GLOBAL_FILTERS,
        "description": "Versteckte App Coupons in Kategorien zeigen*¹",
        "default": True
    },
    "hideDuplicates": {
        "category": SettingCategories.GLOBAL_FILTERS,
        "description": "Duplikate ausblenden |App CP bevorz.",
        "default": False
    },
    "highlightFavoriteCouponsInButtonTexts": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Favoriten in Buttons mit " + SYMBOLS.STAR + " markieren",
        "default": True
    },
    "highlightNewCouponsInCouponButtonTexts": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Neue Coupons in Buttons mit " + SYMBOLS.NEW + " markieren",
        "default": True
    },
    "highlightVeggieCouponsInCouponButtonTexts": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Veggie Coupons in Buttons mit " + SYMBOLS.BROCCOLI + " markieren",
        "default": True
    },
    "displayQR": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "QR Codes zeigen",
        "default": True
    },
    "displayCouponSortButton": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Coupon sortieren Button zeigen",
        "default": True
    },
    "enableTerminalMode": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Terminal Modus | LangPLU in Buttons zeigen",
        "default": False
    },
    "notifyWhenFavoritesAreBack": {
        "category": SettingCategories.NOTIFICATIONS,
        "description": "Favoriten Benachrichtigungen",
        "default": False
    },
    "notifyWhenNewCouponsAreAvailable": {
        "category": SettingCategories.NOTIFICATIONS,
        "description": "Benachrichtigung bei neuen Coupons",
        "default": False
    },
    "notifyMeAsAdminIfThereAreProblems": {
        "category": SettingCategories.NOTIFICATIONS,
        "description": "Admin Benachrichtigung bei Problemen",
        "default": True
    },
    "notifyOnBotNewsletter": {
        "category": SettingCategories.NOTIFICATIONS,
        "description": "BetterKing TG Newsletter",
        "default": True
    },
    "autoDeleteExpiredFavorites": {
        "category": SettingCategories.MISC,
        "description": "Abgelaufene Favoriten automatisch löschen",
        "default": False
    }
}

# Enable this to show BETA setting to users --> Only enable this if there are beta features available
# 2022-02-19: Keep this enabled as a dummy although there are no BETA features as disabling it would possibly render the "Reset settings to default" function useless
DISPLAY_BETA_SETTING = False

""" This is a helper for basic user on/off settings """
if DISPLAY_BETA_SETTING:
    USER_SETTINGS_ON_OFF["enableBetaFeatures"] = {
        "description": "Beta Features aktivieren",
        "default": False
    }


def removeDuplicatedCoupons(coupons: Union[List[Coupon], dict]) -> dict:
    couponTitleMappingTmp = getCouponTitleMapping(coupons)
    # Now clean our mapping: Sometimes one product may be available twice with multiple prices -> We want exactly one mapping per title
    couponsWithoutDuplicates = {}
    for normalizedTitle, coupons in couponTitleMappingTmp.items():
        couponsForDuplicateRemoval = []
        for coupon in coupons:
            if coupon.isEligibleForDuplicateRemoval():
                couponsForDuplicateRemoval.append(coupon)
            else:
                # We cannot remove this coupon as duplicate by title -> Add it to our final results list
                couponsWithoutDuplicates[coupon.id] = coupon
        # Check if anything is left to do
        if len(couponsForDuplicateRemoval) == 0:
            continue
        # Sort these ones by price and pick the first (= cheapest) one for our mapping.
        isDifferentPrices = False
        firstPrice = None
        appCoupon = None
        if len(couponsForDuplicateRemoval) == 1:
            coupon = couponsForDuplicateRemoval[0]
            couponsWithoutDuplicates[coupon.id] = coupon
            continue
        for coupon in couponsForDuplicateRemoval:
            if firstPrice is None:
                firstPrice = coupon.getPrice()
            elif coupon.getPrice() != firstPrice:
                isDifferentPrices = True
            if coupon.type == CouponType.APP:
                appCoupon = coupon
        if isDifferentPrices:
            # Prefer cheapest coupon
            couponsSorted = sortCouponsByPrice(couponsForDuplicateRemoval)
            coupon = couponsSorted[0]
        elif appCoupon is not None:
            # Same prices but different sources -> Prefer App coupon
            coupon = appCoupon
        else:
            # Same prices but all coupons are from the same source -> Should never happen but we'll cover it anyways -> Select first item.
            coupon = couponsForDuplicateRemoval[0]
        couponsWithoutDuplicates[coupon.id] = coupon
    numberofRemovedDuplicates = len(coupons) - len(couponsWithoutDuplicates)
    logging.debug("Number of removed duplicates: " + str(numberofRemovedDuplicates))
    return couponsWithoutDuplicates


def sortCoupons(coupons: Union[list, dict], sortCode: Union[int, CouponSortMode]) -> dict:
    coupons = sortCouponsAsList(coupons, sortCode)
    filteredAndSortedCouponsDict = {}
    for coupon in coupons:
        filteredAndSortedCouponsDict[coupon.id] = coupon
    return filteredAndSortedCouponsDict


def sortCouponsAsList(coupons: Union[list, dict], sortCode: Union[int, CouponSortMode]) -> dict:
    if isinstance(coupons, dict):
        coupons = list(coupons.values())
    if isinstance(sortCode, CouponSortMode):
        sortMode = sortCode
    else:
        sortMode = getSortModeBySortCode(sortCode)
    if sortMode == CouponSortModes.TYPE_MENU_PRICE:
        couponsWithoutFriesAndDrink = []
        couponsWithFriesAndDrink = []
        allContainedCouponTypes = []
        for coupon in coupons:
            if coupon.type not in allContainedCouponTypes:
                allContainedCouponTypes.append(coupon.type)
            if coupon.isContainsFriesAndDrink():
                couponsWithFriesAndDrink.append(coupon)
            else:
                couponsWithoutFriesAndDrink.append(coupon)
        couponsWithoutFriesAndDrink = sortCouponsByPrice(couponsWithoutFriesAndDrink)
        couponsWithFriesAndDrink = sortCouponsByPrice(couponsWithFriesAndDrink)
        # Merge them together again.
        coupons = couponsWithoutFriesAndDrink + couponsWithFriesAndDrink
        # App coupons(source == 0) > Paper coupons
        allContainedCouponTypes.sort()
        # Separate sorted coupons by type
        couponsSeparatedByType = {}
        for couponType in allContainedCouponTypes:
            couponsTmp = list(filter(lambda x: x.type == couponType, coupons))
            couponsSeparatedByType[couponType] = couponsTmp
        # Put our list sorted by type together again -> Sort done
        coupons = []
        for allCouponsOfOneSourceType in couponsSeparatedByType.values():
            coupons += allCouponsOfOneSourceType
    elif sortMode == CouponSortModes.MENU_PRICE:
        couponsWithoutFriesAndDrink = []
        couponsWithFriesAndDrink = []
        for coupon in coupons:
            if coupon.isContainsFriesAndDrink():
                couponsWithFriesAndDrink.append(coupon)
            else:
                couponsWithoutFriesAndDrink.append(coupon)
        couponsWithoutFriesAndDrink = sortCouponsByPrice(couponsWithoutFriesAndDrink)
        couponsWithFriesAndDrink = sortCouponsByPrice(couponsWithFriesAndDrink)
        # Merge them together again.
        coupons = couponsWithoutFriesAndDrink + couponsWithFriesAndDrink
    elif sortMode == CouponSortModes.PRICE:
        coupons = sortCouponsByPrice(coupons)
    elif sortMode == CouponSortModes.PRICE_DESCENDING:
        coupons = sortCouponsByPrice(coupons, descending=True)
    elif sortMode == CouponSortModes.DISCOUNT:
        coupons = sortCouponsByDiscount(coupons)
    elif sortMode == CouponSortModes.DISCOUNT_DESCENDING:
        coupons = sortCouponsByDiscount(coupons, descending=True)
    elif sortMode == CouponSortModes.NEW:
        coupons = sortCouponsByNew(coupons)
    elif sortMode == CouponSortModes.NEW_DESCENDING:
        coupons = sortCouponsByNew(coupons, descending=True)
    else:
        # This should never happen
        logging.warning("Developer mistake!! Unknown sortMode: " + str(sortMode))
    return coupons
