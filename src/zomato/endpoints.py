"""Zomato web API endpoint map.

Discovered from frontend JS bundles at zwstatic.zomato.com and
server-side rendering at www.zomato.com. All endpoints are relative
to https://www.zomato.com unless prefixed with a full URL.
"""

# Base URLs
ZOMATO_BASE = "https://www.zomato.com"
DISTRICT_BASE = "https://www.district.in"
JUMBO_BASE = "https://jumbo.zomato.com"

# Auth
CSRF = "/webroutes/auth/csrf"

# Location
LOCATION_GET = "/webroutes/location/get"
LOCATION_SEARCH = "/webroutes/location/search"
LOCATION_GEO_DATA = "/webroutes/location/locationGeoData"

# Search
SEARCH_HOME = "/webroutes/search/home"
SEARCH_AUTOSUGGEST = "/webroutes/search/autoSuggest"
SEARCH_APPLY_FILTER = "/webroutes/search/applyFilter"
SEARCH_API_LEGACY = "/webapi/searchapi.php"

# Page (SSR data fetcher — the primary way to get restaurant listings)
GET_PAGE = "/webroutes/getPage"

# Home
HOME_QUICK_LINKS = "/webroutes/home/quickLinks"
HOME_O2_QUICK_LINKS = "/webroutes/home/o2quickLinks"

# Restaurant
RESTAURANT_INFO = "/webroutes/restaurant/info"
RESTAURANT_BOOKMARK = "/webroutes/restaurant/bookmark"
RESTAURANT_RATE = "/webroutes/restaurant/rate"
RESTAURANT_SHARE = "/webroutes/restaurant/share"
RESTAURANT_USER_MODAL_INFO = "/webroutes/restaurant/userModalInfo"
RESTAURANT_HYGIENE = "/webroutes/restaurant/getHygieneDetails"
RESTAURANT_HYPERPURE = "/webroutes/restaurant/getHyperpureDetails"

# Reviews
REVIEWS_LOAD_MORE = "/webroutes/reviews/loadMore"
REVIEWS_POST = "/webroutes/reviews/post"
REVIEWS_DELETE = "/webroutes/reviews/delete"
REVIEWS_LIKE = "/webroutes/reviews/likeReview"
REVIEWS_FOLLOW = "/webroutes/reviews/follow"
REVIEWS_SORT = "/webroutes/reviews/sortReviews"
REVIEWS_SWITCH_TAB = "/webroutes/reviews/switchTab"
REVIEWS_SUGGEST_TAGS = "/webroutes/reviews/suggestTags"
REVIEWS_COMMENT_POST = "/webroutes/reviews/comment/post"
REVIEWS_COMMENT_DELETE = "/webroutes/reviews/comment/delete"
REVIEWS_COMMENT_LOAD_MORE = "/webroutes/reviews/comment/loadMore"

# Photos
PHOTOS_GALLERY = "/webroutes/photos/viewGallery"
PHOTOS_LOAD_MORE = "/webroutes/photos/loadMore"
PHOTOS_UPLOAD = "/webroutes/photos/upload"
PHOTOS_SUBMIT = "/webroutes/photos/submitPhoto"
PHOTOS_LIKE = "/webroutes/photos/like"
PHOTOS_COMMENT_POST = "/webroutes/photos/comment/post"
PHOTOS_COMMENT_DELETE = "/webroutes/photos/comment/delete"

# Menu
MENU_VIEW = "/webroutes/menu/viewMenu"

# Offers
ORDER_RES_OFFER = "/webroutes/order/resOffer"

# Kitchen (Zomato Kitchen / commercial)
KITCHEN_CITY = "/webroutes/kitchen/city"
KITCHEN_LEADS = "/webroutes/kitchen/leads"

# Blog
BLOG_POSTS = "/webroutes/blog/posts"

# Awards
AWARDS_WINNERS = "/webroutes/awards/winners/"

# Sneakpeek
SNEAKPEEK = "/webroutes/sneakpeek"

# Collections
COLLECTION_SAVE = "/webroutes/collection/saveCollection"

# Dining (Dine-out gateway)
DINING_CART_CHECKOUT = "/dining-gw/consumer/web/cart/checkout"
DINING_CART_GET = "/dining-gw/consumer/web/cart/get"
DINING_ORDER_CANCEL = "/dining-gw/consumer/web/order/cancel"
DINING_ORDER_DETAILS = "/dining-gw/consumer/web/order/details"
DINING_RESTAURANT_ADS = "/dining-gw/consumer/web/restaurant/ads"
DINING_ORDER_HISTORY = "/dining-gw/consumer/web/tr/order-history"
DINING_SLOTS = "/dining-gw/consumer/web/tr/slots"
DINING_UPCOMING_BOOKING = "/dining-gw/consumer/web/upcoming-booking/get"

# Booking
BOOK_TIME_SLOTS = "/webroutes/book/getTimeSlots"
BOOK_MAKE_BOOKING = "/webroutes/book/makeBooking"
BOOK_CANCEL = "/webroutes/book/cancelBooking"
BOOK_MODIFY = "/webroutes/book/modifyBooking"

# Zomaland / Zlive (Events on Zomato)
ZLIVE_BUILD_CART = "/webroutes/zlive/buildCart"
ZLIVE_BOOK_TICKETS = "/webroutes/zlive/bookTickets"
ZLIVE_PAYMENT_RESPONSE = "/webroutes/zlive/paymentResponse"
ZOMALAND_GET_ORDER = "/webroutes/zomaland/get-order"
ZOMALAND_CANCEL_TICKET = "/webroutes/zomaland/cancel-ticket"
ZOMALAND_TICKET_HISTORY = "/webroutes/zomaland/ticket-history"

# User
USER_ORDERS = "/webroutes/user/orders"
USER_BOOKMARKS = "/webroutes/user/bookmarks"
USER_REVIEWS = "/webroutes/user/reviews"
USER_PHOTOS = "/webroutes/user/photos"
USER_BLOGS = "/webroutes/user/blogs"
USER_NETWORK = "/webroutes/user/network"
USER_NOTIFICATIONS = "/webroutes/user/notifications"
USER_BOOKING = "/webroutes/user/booking"
USER_BOOKING_INFO = "/webroutes/user/booking/info"
USER_CDNG_ORDERS = "/webroutes/user/cdngOrders"
USER_PROFILE_PIC = "/webroutes/user/profilePic"
USER_EDIT_PROFILE = "/webroutes/user/editProfile"

# Promo
PROMO_INFO = "/webroutes/promo/info"

# District (Events) — Next.js RSC pages
DISTRICT_EVENTS_PAGE = "/events"
DISTRICT_MOVIES_PAGE = "/movies"
DISTRICT_HOME = "/"
DISTRICT_VENUE_PAGE = "/gw/consumer/event/venue-page-web"
DISTRICT_WEB_CLIENT_ID = "district-web"
DISTRICT_WEB_APP_TYPE = "WEB"
DISTRICT_WEB_APP_VERSION = "11.11.1"
DISTRICT_GUEST_TOKEN = "1212"

# Events gateway (from RSC data)
EVENTS_REMINDER_SET = "/gw/consumer/dining/reminder/set"


# All read-only endpoints safe for smoke testing
READ_ONLY_ENDPOINTS = [
    CSRF,
    LOCATION_GET,
    LOCATION_SEARCH,
    LOCATION_GEO_DATA,
    SEARCH_AUTOSUGGEST,
    GET_PAGE,
    HOME_QUICK_LINKS,
    HOME_O2_QUICK_LINKS,
    RESTAURANT_INFO,
    RESTAURANT_HYGIENE,
    RESTAURANT_HYPERPURE,
    REVIEWS_LOAD_MORE,
    REVIEWS_SORT,
    REVIEWS_SWITCH_TAB,
    REVIEWS_SUGGEST_TAGS,
    REVIEWS_COMMENT_LOAD_MORE,
    PHOTOS_GALLERY,
    PHOTOS_LOAD_MORE,
    MENU_VIEW,
    ORDER_RES_OFFER,
    KITCHEN_CITY,
    BLOG_POSTS,
    AWARDS_WINNERS,
    SNEAKPEEK,
]

# All write/mutating endpoints (never called during discovery/smoke)
WRITE_ENDPOINTS = [
    RESTAURANT_BOOKMARK,
    RESTAURANT_RATE,
    RESTAURANT_SHARE,
    REVIEWS_POST,
    REVIEWS_DELETE,
    REVIEWS_LIKE,
    REVIEWS_FOLLOW,
    REVIEWS_COMMENT_POST,
    REVIEWS_COMMENT_DELETE,
    PHOTOS_UPLOAD,
    PHOTOS_SUBMIT,
    PHOTOS_LIKE,
    PHOTOS_COMMENT_POST,
    PHOTOS_COMMENT_DELETE,
    COLLECTION_SAVE,
    BOOK_MAKE_BOOKING,
    BOOK_CANCEL,
    BOOK_MODIFY,
    ZLIVE_BUILD_CART,
    ZLIVE_BOOK_TICKETS,
    ZOMALAND_CANCEL_TICKET,
]