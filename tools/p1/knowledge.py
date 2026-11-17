"""Static knowledge tables for the Stage 1 library and integration detectors.

Everything here is *recognition by name*: a unit that matches a family is
evidence that the family is referenced, never proof that it is installed,
licensed or the same version.  The tables are plain data so a reviewer can
audit them, and every pattern is anchored (``fullmatch``) so a unit that
merely *contains* a library name (``IdleHelper``, ``QRCodeGen``) does not match.

Two matching modes exist because Pascal identifiers are case-insensitive but
vendor prefixes are conventionally cased: ``ci`` patterns run on the lower-
cased name, ``cs`` patterns on the name as written (``Id[A-Z]`` matches
``IdHTTP`` but not ``Identity``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "Family",
    "FAMILIES",
    "PACKAGE_TABLE",
    "match_family",
    "IntegrationRule",
    "INTEGRATION_RULES",
    "CLASS_RULES",
    "UNIT_RULES",
    "IDENT_RULES",
    "SYSTEM_DLLS",
    "DB_CLIENT_LIBRARIES",
    "FIREDAC_DRIVER_CLIENT",
    "TECH_CLIENT",
    "ignored_url_host",
]


def _rx(patterns: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p) for p in patterns)


# --------------------------------------------------------------------------
# Library families
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Family:
    """A recognised library and how its unit names look."""

    name: str
    category: str  # LIBRARY_CATEGORIES
    vendor: str
    #: Origin when the library is recognised but absent from the input.
    absent_origin: str = "external"
    exact: frozenset[str] = frozenset()
    ci: tuple[re.Pattern[str], ...] = ()
    cs: tuple[re.Pattern[str], ...] = ()
    exclude: frozenset[str] = field(default_factory=frozenset)

    def matches(self, name: str) -> bool:
        low = name.lower()
        if low in self.exclude:
            return False
        if low in self.exact:
            return True
        if any(p.fullmatch(low) for p in self.ci):
            return True
        return any(p.fullmatch(name) for p in self.cs)


def _fam(name: str, category: str, vendor: str, *, exact: str = "",
         ci: tuple[str, ...] = (), cs: tuple[str, ...] = (),
         origin: str = "external", exclude: str = "") -> Family:
    return Family(
        name=name, category=category, vendor=vendor, absent_origin=origin,
        exact=frozenset(exact.split()), ci=_rx(ci), cs=_rx(cs),
        exclude=frozenset(exclude.split()),
    )


#: Order matters: the first family that matches a unit wins.
FAMILIES: tuple[Family, ...] = (
    # --- units shipped with the compilers that dialects.classify_unit does
    #     not list; same names as its categories so findings merge ---------
    _fam("SOAP (RTL)", "networking", "", origin="rtl",
         exact="invokeregistry soaphttpclient soaphttptrans soaphttppasinv "
               "soapconn soapdm rio wsdlbind wsdlintf wsdlitems "
               "opconvertoptions webnode soapattachintf xsbuiltins"),
    _fam("Windows platform units", "rtl", "", origin="rtl",
         exact="winsock winsock2 wininet winhttp urlmon mapi winspool "
               "tlhelp32 psapi winsvc svcmgr shfolder commctrl richedit "
               "uxtheme multimon dwmapi mmsystem olectrls axctrls olectnrs "
               "winapi.winsock winapi.winsock2 winapi.wininet "
               "winapi.winhttp winapi.urlmon winapi.mapi winapi.winspool "
               "winapi.winsvc vcl.svcmgr"),
    _fam("VCL", "framework", "", origin="framework",
         exact="printers clipbrd jpeg appevnts extdlgs filectrl gifimg "
               "pngimage tabs tabnotbk outline spin colorgrd valedit "
               "consts vcl.printers vcl.clipbrd"),
    # --- data access shipped with the compilers ---------------------------
    _fam("FireDAC", "database", "Embarcadero", origin="rtl",
         ci=(r"firedac[\w.]*",
             r"uad(?:comp|stan|phys|dats|guix|ptl|vclui|console)\w*")),
    _fam("BDE", "database", "Embarcadero", origin="rtl",
         exact="dbtables bde bdeconst bdecds"),
    _fam("ADO", "database", "Embarcadero", origin="rtl",
         exact="ado adodb adoint adoconst oledb data.win.adodb"),
    _fam("dbExpress", "database", "Embarcadero", origin="rtl",
         exact="sqlexpr data.sqlexpr dbxcommon data.dbxcommon sqlconst "
               "sqltimst dbexpress dbx dbxdynalink",
         ci=(r"dbx\w+", r"data\.dbx\w*")),
    _fam("IBX", "database", "Embarcadero", origin="rtl",
         exact="ibase ibxfiles fbintf firebird",
         ci=(r"ib(?:database|sql|query|table|customdataset|storedproc|events|"
             r"updatesql|services|xml|header|intf|monitor|extract|dataset|"
             r"script|utils|blob|batch|file|const|eventnotifier)\w*",
             r"ibx(?:\.\w+)*")),
    _fam("SQLdb", "database", "Free Pascal", origin="rtl",
         exact="sqldb sqldbtypes sqlite3conn pqconnection ibconnection "
               "odbcconn oracleconnection mssqlconn bufdataset sqlscript",
         ci=(r"mysql\d+conn",)),
    _fam("SQLite", "database", "SQLite wrappers",
         exact="sqlite3 sqlite3dyn sqlite3wrap sqlite3ds sqlite3api"),
    _fam("DataSnap", "database", "Embarcadero", origin="rtl",
         exact="dbclient midas provider dsnap dsnapcon",
         ci=(r"datasnap[\w.]*",)),
    _fam("DB (TDataSet)", "database", "Embarcadero / Free Pascal",
         origin="rtl",
         exact="db data.db dbctrls dbgrids vcl.dbctrls vcl.dbgrids dbcgrids "
               "vcl.dbcgrids dbcommon data.dbcommon dblookup vcl.dblookup "
               "memdataset"),
    # --- data access, third party -----------------------------------------
    _fam("Zeos", "database", "Zeos Development Group",
         ci=(r"zeos\w*", r"zconnection", r"zdataset", r"zabstract\w*",
             r"zdbc\w*", r"zsqlprocessor", r"zsqlmonitor", r"zcompatibility",
             r"zplain\w*"),
         cs=(r"Z(?:Connection|Dataset|Abstract|Dbc|Sql|Plain|Compat|Classes|"
             r"Common|Messages|Exception|Tokenizer|Collections|Variants|Url|"
             r"Sequence|Metadata|Pooled|Events|Proxy|Stored|Object|Memory|"
             r"Intf|Free)\w*",)),
    _fam("UniDAC", "database", "Devart", exact="uni dbaccess memds memdata "
         "dbmonitor",
         ci=(r"unidac\w*", r"uni(?:provider|script|dump|loader|alerter)\w*",
             r"(?:ora|my|pg|lite|sdac|sql)access", r"odac\w*", r"mydac\w*")),
    # --- networking --------------------------------------------------------
    _fam("Indy", "networking", "Indy Pit Crew",
         ci=(r"indy\w*",
             r"id(?:global|http|tcp|udp|ftp|smtp|pop3|imap4|message|mime|ssl|"
             r"socket|stack|base|component|exception|ip|dns|coder|hash|sasl|"
             r"ntlm|cookie|intercept|iohandler|context|scheduler|thread|zlib|"
             r"log|status|uri|tunnel|icmp|telnet|nntp|ldap)\w*"),
         cs=(r"Id[A-Z0-9]\w*",)),
    _fam("Synapse", "networking", "Ararat Synapse",
         exact="blcksock synautil synaser httpsend ftpsend smtpsend pop3send "
               "imapsend ldapsend synacode synsock ssl_openssl ssl_cryptlib "
               "ssl_openssl_lib sntpsend tlntsend dnssend pingsend snmpsend "
               "synafpc synachar mimepart mimemess mimeinln synaip synamisc "
               "synadbg clamsend nntpsend asn1util ssl_streamsec ssl_sbb"),
    _fam("ICS", "networking", "Overbyte",
         ci=(r"overbyteics\w*", r"ics\.\w+(?:\.\w+)*"),
         cs=(r"Ics[A-Z]\w*",)),
    # --- frameworks and utilities -----------------------------------------
    _fam("mORMot", "other", "Synopse",
         ci=(r"mormot(?:\.\w+)*", r"syn(?:commons|table|sqlite3|db\w*|"
             r"crtsock|log|crypto|zip|ole|mongodb|pdf|gdiplus|ztypes|"
             r"bidirsock|selftests|opengl)")),
    _fam("SynEdit", "ui-components", "SynEdit",
         ci=(r"synedit\w*(?:\.\w+)*", r"synhighlighter\w*", r"synmemo",
             r"syncompletionproposal", r"syntexthighlighter", r"synunicode",
             r"synexport\w*", r"synautocorrect\w*", r"synregexpr",
             r"synmacrorecorder", r"syndbedit", r"synplugins\w*")),
    # --- UI component suites ----------------------------------------------
    _fam("DevExpress", "ui-components", "Developer Express",
         cs=(r"(?:cx|dx)[A-Z]\w*",),
         ci=(r"(?:cx|dx)(?:grid|edit|container|style|data|dbdata|"
             r"lookandfeel\w*|classes|common|graphics|treelist|barmanager|"
             r"bar|ribbon|layout\w*|nav\w*|tab\w*|page\w*|scheduler|pivot\w*|"
             r"spreadsheet|printing\w*|gdi\w*|skin\w*|theme\w*|filter\w*|"
             r"customize\w*|vgrid|gantt|localizer\w*)\w*",),
         exclude="dxtypes dxgi dxsdk dxerr dxutil dxutils dxfile dxflib dxf"),
    _fam("TMS", "ui-components", "TMS Software",
         cs=(r"Tms[A-Z]\w*", r"Adv[A-Z]\w*", r"Asg[A-Z]\w*"),
         ci=(r"tms\.\w+(?:\.\w+)*", r"tmsvcl\w*"),
         exclude="advapi32 advapi"),
    _fam("JEDI", "ui-components", "Project JEDI", cs=(r"Jv[A-Z]\w*",)),
    _fam("JCL", "utility", "Project JEDI", cs=(r"Jcl[A-Z]\w*",),
         ci=(r"jcl[a-z]\w*",)),
    _fam("JWA", "other", "Project JEDI", ci=(r"jwa[a-z]\w*",)),
    _fam("Raize", "ui-components", "Raize Software",
         cs=(r"Rz[A-Z]\w*",), ci=(r"raize\.\w+(?:\.\w+)*",)),
    _fam("VirtualTrees", "ui-components", "Virtual TreeView",
         exact="virtualtreeview virtualstringtree virtualexplorertree "
               "virtualshellutilities",
         ci=(r"virtualtrees(?:\.\w+)*", r"virtualtree\w*")),
    _fam("RxLib", "ui-components", "Rx Library",
         ci=(r"rx(?:dbutils|ctrls|dates|split|lookup|gif|slider|toolbar|"
             r"clock|cur|dbctrl|dbgrid|mrulist|speedbar|tooledit|hints|"
             r"menus|labels|durable)\w*",)),
    _fam("TeeChart", "ui-components", "Steema",
         ci=(r"tee(?:ngine|procs?|const|shape|draw|about|opengl|gdiplus|"
             r"tree|funcs?|export|edit|chart)\w*",)),
    # --- reporting -------------------------------------------------------------
    _fam("FastReport", "reporting", "Fast Reports",
         ci=(r"frx[a-z]\w*", r"fs_[a-z]\w*")),
    _fam("QuickReport", "reporting", "QBS Software",
         ci=(r"quickrpt", r"qr(?!code|cod|gen|enc|dec|scan)[a-z]\w*")),
    _fam("ReportBuilder", "reporting", "Digital Metaphors",
         cs=(r"pp[A-Z]\w*",)),
    _fam("Rave", "reporting", "Nevrona",
         ci=(r"rv(?:class|define|cs\w*|proj|data\w*|tool|util|ld\w*|std|db\w*|"
             r"custom|sys|render\w*|device\w*)",)),
    _fam("Crystal Reports", "reporting", "SAP",
         exact="crpe32 ucrpe32 crpe ucrpe crystalreport", ci=(r"crystal\w*",)),
    _fam("LazReport", "reporting", "Lazarus", ci=(r"lr_\w+", r"lazreport\w*")),
    # --- utilities and test frameworks ------------------------------------
    _fam("FastMM", "utility", "Pierre le Riche", ci=(r"fastmm\w*",)),
    _fam("Spring4D", "utility", "Spring4D", ci=(r"spring(?:\.\w+)*",)),
    _fam("DUnitX", "utility", "DUnitX", ci=(r"dunitx(?:\.\w+)*",)),
    _fam("DUnit", "utility", "DUnit",
         exact="testframework guitestrunner texttestrunner testextensions "
               "xmltestrunner", ci=(r"dunit\w*",)),
    _fam("FPCUnit", "utility", "Free Pascal", origin="rtl",
         exact="fpcunit testregistry consoletestrunner testdecorator "
               "xmlreporter"),
    _fam("OmniThreadLibrary", "utility", "Primoz Gabrijelcic",
         cs=(r"Otl[A-Z]\w*",), ci=(r"omnithread\w*",)),
    _fam("madExcept", "utility", "madshi",
         ci=(r"madexcept\w*", r"madtypes", r"madlist", r"madlinkdisasm")),
    _fam("EurekaLog", "utility", "Neos Eureka", ci=(r"eurekalog\w*",)),
    # --- crypto ------------------------------------------------------------
    _fam("OpenSSL", "crypto", "OpenSSL", exact="opensslsockets",
         ci=(r"openssl\w*", r"libeay\w*", r"ssleay\w*")),
    _fam("LockBox", "crypto", "TurboPower / LockBox",
         ci=(r"utplb_\w+", r"lockbox\w*")),
    _fam("DCPcrypt", "crypto", "DCPcrypt", ci=(r"dcp[a-z0-9_]{3,}",)),
    # --- compression -------------------------------------------------------
    _fam("Abbrevia", "compression", "TurboPower / Abbrevia",
         cs=(r"Ab[A-Z][a-z]\w*",),
         ci=(r"ab(?:zipper|unzper|arctyp|base|browse|const|utils|zipprc|"
             r"zipapi|ziptyp|zipcomp|vclutils|meter|views|zbrows|ctmenu|"
             r"tarprc|gztyp|cabtyp|cabkit|extrct|bzip2typ|lzmatyp)\w*",)),
    _fam("ZLib", "compression", "zlib / RTL", origin="rtl",
         exact="zlib system.zlib paszlib zstream zip system.zip zipper"),
    _fam("ZLibEx", "compression", "Roberto Della Pasqua", ci=(r"zlibex\w*",)),
    _fam("ZipForge", "compression", "ComponentAce",
         ci=(r"zipforge\w*", r"archiveforge\w*")),
    _fam("ZipMaster", "compression", "ZipMaster",
         ci=(r"zipmstr\w*", r"zipmaster\w*")),
    _fam("SevenZip", "compression", "7-Zip bindings", ci=(r"sevenzip\w*",)),
    # --- JSON / XML ----------------------------------------------------------
    _fam("SuperObject", "json-xml", "SuperObject",
         ci=(r"superobject\w*",)),
    _fam("XSuperObject", "json-xml", "XSuperObject", exact="xsuperobject"),
    _fam("uLkJSON", "json-xml", "Leon Kassovski", exact="ulkjson"),
    _fam("JsonDataObjects", "json-xml", "Andreas Hausladen",
         exact="jsondataobjects"),
    _fam("System.JSON", "json-xml", "Embarcadero", origin="rtl",
         exact="json data.dbxjson rest.json rest.jsonreflect",
         ci=(r"system\.json(?:\.\w+)*",)),
    _fam("fpJSON", "json-xml", "Free Pascal", origin="rtl",
         exact="fpjson jsonparser jsonscanner jsonreader jsonwriter jsonconf "
               "fpjsonrtti"),
    _fam("OmniXML", "json-xml", "OmniXML", ci=(r"omnixml\w*",)),
    _fam("NativeXml", "json-xml", "Nils Haeck", ci=(r"nativexml\w*",)),
    _fam("OXml", "json-xml", "Ondrej Pokorny", ci=(r"oxml\w*",)),
    _fam("XML (RTL)", "json-xml", "Embarcadero / Free Pascal", origin="rtl",
         exact="xmlread xmlwrite dom sax xpath htmlparser fasthtmlparser "
               "laz2_dom laz2_xmlread laz2_xmlwrite xmldom xmldoc xmlintf "
               "xmlrtl msxmldom xmlxform xsbuiltins xmlschema",
         ci=(r"xml\.\w+(?:\.\w+)*",)),
)


#: Package names (``requires`` clauses, ``.lpi`` required packages) shipped
#: with the compilers: ``name → (library, category, origin)``.
_RTL = ("RTL", "rtl", "rtl")
_VCL = ("VCL", "framework", "framework")
_FMX = ("FMX", "framework", "framework")
_LCL = ("LCL", "framework", "framework")
PACKAGE_TABLE: dict[str, tuple[str, str, str]] = {
    "rtl": _RTL,
    "fcl": ("FPC RTL", "rtl", "rtl"),
    "fcl-base": ("FPC RTL", "rtl", "rtl"),
    "xmlrtl": ("XML (RTL)", "json-xml", "rtl"),
    "inet": ("Internet (RTL)", "networking", "rtl"),
    "soaprtl": ("SOAP (RTL)", "networking", "rtl"),
    "vcl": _VCL, "vclx": _VCL, "vclimg": _VCL, "vclactnband": _VCL,
    "vclie": _VCL, "vclsmp": _VCL, "vcldb": _VCL,
    "fmx": _FMX, "fmxase": _FMX, "fmxobj": _FMX,
    "lcl": _LCL, "lazcontrols": _LCL,
    "dbrtl": ("DB (TDataSet)", "database", "rtl"),
    "adortl": ("ADO", "database", "rtl"),
    "bdertl": ("BDE", "database", "rtl"),
    "dbexpress": ("dbExpress", "database", "rtl"),
    "dbxcds": ("DataSnap", "database", "rtl"),
    "dsnap": ("DataSnap", "database", "rtl"),
    "dsnapcon": ("DataSnap", "database", "rtl"),
    "ibxpress": ("IBX", "database", "rtl"),
    "designide": ("IDE design-time", "other", "rtl"),
    "vcldesigner": ("IDE design-time", "other", "rtl"),
}


def match_family(name: str) -> Family | None:
    """First family matching *name* or its last dotted segment."""

    candidates = [name]
    if "." in name:
        candidates.append(name.rsplit(".", 1)[1])
    for family in FAMILIES:
        if any(family.matches(c) for c in candidates):
            return family
    return None


# --------------------------------------------------------------------------
# Integration rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class IntegrationRule:
    """Units, classes and API identifiers that evidence one integration."""

    category: str  # INTEGRATION_CATEGORIES
    technology: str
    units: frozenset[str] = frozenset()
    unit_re: tuple[re.Pattern[str], ...] = ()
    classes: frozenset[str] = frozenset()
    class_re: tuple[re.Pattern[str], ...] = ()
    idents: frozenset[str] = frozenset()
    #: ``True`` for servers/listeners (a ``Port`` literal is an endpoint).
    listener: bool = False

    def match_unit(self, name: str) -> bool:
        low = name.lower()
        tail = low.rsplit(".", 1)[-1]
        if low in self.units or tail in self.units:
            return True
        return any(p.fullmatch(low) or p.fullmatch(tail)
                   for p in self.unit_re)

    def match_class(self, low: str) -> bool:
        return low in self.classes or any(
            p.fullmatch(low) for p in self.class_re)


def _rule(category: str, technology: str, *, units: str = "",
          unit_re: tuple[str, ...] = (), classes: str = "",
          class_re: tuple[str, ...] = (), idents: str = "",
          listener: bool = False) -> IntegrationRule:
    return IntegrationRule(
        category=category, technology=technology,
        units=frozenset(units.split()), unit_re=_rx(unit_re),
        classes=frozenset(classes.split()), class_re=_rx(class_re),
        idents=frozenset(idents.split()), listener=listener,
    )


INTEGRATION_RULES: tuple[IntegrationRule, ...] = (
    # Indy
    _rule("http-client", "Indy", units="idhttp idhttpheaderinfo",
          classes="tidhttp"),
    _rule("ftp", "Indy", units="idftp idftpcommon idftplist",
          classes="tidftp"),
    _rule("email", "Indy",
          units="idsmtp idpop3 idimap4 idmessage idmessageclient "
                "idsmtpserver idpop3server",
          classes="tidsmtp tidpop3 tidimap4 tidmessage"),
    _rule("socket", "Indy",
          units="idtcpclient idtcpserver idudpclient idudpserver "
                "idcustomtcpserver idtcpconnection",
          classes="tidtcpclient tidtcpserver tidudpclient tidudpserver",
          listener=True),
    _rule("http-server", "Indy",
          units="idhttpserver idcustomhttpserver idhttpwebbrokerbridge",
          classes="tidhttpserver tidhttpwebbrokerbridge", listener=True),
    # Synapse
    _rule("http-client", "Synapse", units="httpsend", classes="thttpsend"),
    _rule("ftp", "Synapse", units="ftpsend", classes="tftpsend"),
    _rule("email", "Synapse", units="smtpsend pop3send imapsend",
          classes="tsmtpsend tpop3send timapsend"),
    _rule("ldap", "Synapse", units="ldapsend", classes="tldapsend"),
    _rule("socket", "Synapse", units="blcksock synsock",
          classes="ttcpblocksocket tudpblocksocket"),
    _rule("serial-port", "Synapse", units="synaser", classes="tblockserial"),
    # ICS
    _rule("http-client", "ICS",
          unit_re=(r".*overbyteics(?:httpprot|httpcli)\w*",),
          classes="thttpcli"),
    _rule("ftp", "ICS", unit_re=(r".*overbyteicsftpcli\w*",),
          classes="tftpclient"),
    _rule("email", "ICS",
          unit_re=(r".*overbyteics(?:smtpprot|pop3prot)\w*",),
          classes="tsmtpcli tsyncsmtpcli"),
    _rule("socket", "ICS", unit_re=(r".*overbyteicswsocket\w*",),
          classes="twsocket twsocketserver", listener=True),
    # Windows internet APIs and the RTL
    _rule("http-client", "WinInet", units="wininet winapi.wininet",
          idents="internetopen internetopenurl internetreadfile "
                 "httpopenrequest httpsendrequest"),
    _rule("http-client", "WinHTTP", units="winhttp winapi.winhttp",
          idents="winhttpopen winhttpconnect winhttpsendrequest"),
    _rule("http-client", "URLMon", units="urlmon winapi.urlmon",
          idents="urldownloadtofile urldownloadtocachefile"),
    _rule("ftp", "WinInet", idents="ftpgetfile ftpputfile ftpopenfile "
                                   "ftpfindfirstfile ftpdeletefile"),
    _rule("http-client", "System.Net.HttpClient",
          units="system.net.httpclient system.net.urlclient "
                "system.net.httpclientcomponent",
          classes="thttpclient tnethttpclient"),
    _rule("http-client", "REST Client Library",
          unit_re=(r"rest\.client", r"rest\.types", r"rest\.authenticator\.\w+"),
          classes="trestclient trestrequest"),
    _rule("http-client", "fphttpclient", units="fphttpclient opensslsockets",
          classes="tfphttpclient"),
    _rule("http-client", "libcurl", units="libcurl curl"),
    _rule("http-server", "WebBroker",
          units="httpapp web.httpapp webreq web.webreq webbroker "
                "web.webbroker webadapt web.webadapt cgiapp web.cgiapp "
                "isapiapp web.win.isapiapp isapi2 winapi.isapi2",
          classes="twebmodule twebappcomponents twebdispatcher "
                  "twebapplication", listener=True),
    _rule("http-server", "fpWeb",
          units="fphttpserver fpweb fphttpapp fpcgi httproute httpdefs "
                "custweb custcgi custfcgi", classes="tfphttpserver",
          listener=True),
    _rule("http-server", "mORMot",
          unit_re=(r"mormot\.net\.server", r"mormot\.rest\.http\.server"),
          units="synbidirsock syncrtsock", listener=True),
    _rule("rpc", "DataSnap", unit_re=(r"datasnap\.ds\w+", r"ds(?:server|"
          r"tcpservertransport|httpservice|httpwebdispatcher)\w*"),
          classes="tdsserver tdstcpservertransport tdshttpservice",
          listener=True),
    _rule("rpc", "RemObjects SDK", unit_re=(r"uro[a-z]\w*",),
          classes="troclient"),
    _rule("rpc", "CORBA", units="corba orbpas corbaobj corbacon",
          classes="tcorbaconnection"),
    _rule("rpc", "XML-RPC", unit_re=(r"xmlrpc\w*", r"jsonrpc\w*")),
    # SOAP
    _rule("soap-webservice", "SOAP",
          units="soaphttpclient soaphttptrans soaphttppasinv soapconn "
                "soapdm invokeregistry wsdlbind wsdlintf wsdlitems rio "
                "web.soaphttpclient web.soaphttptrans",
          classes="thttprio tsoapconnection thttpsoapdispatcher "
                  "thttpsoappascalinvoker twsdlview tsoapwebmodule",
          listener=True),
    # Sockets
    _rule("socket", "Winsock",
          units="winsock winapi.winsock winsock2 winapi.winsock2 scktcomp "
                "system.win.scktcomp",
          classes="tclientsocket tserversocket",
          idents="wsastartup wsacleanup wsagetlasterror gethostbyname "
                 "getaddrinfo inet_addr inet_ntoa", listener=True),
    _rule("socket", "Sockets (RTL)", units="sockets system.win.sockets",
          classes="ttcpclient ttcpserver tudpsocket", listener=True),
    _rule("socket", "ssockets", units="ssockets",
          classes="ttcpserver tinetserver", listener=True),
    # E-mail
    _rule("email", "MAPI", units="mapi winapi.mapi",
          idents="mapisendmail mapilogon mapisenddocuments"),
    # Messaging
    _rule("messaging", "MQTT", unit_re=(r"mqtt\w*",),
          classes="tmqttclient tmqttserver"),
    _rule("messaging", "AMQP", unit_re=(r"amqp\w*", r"rabbitmq\w*"),
          classes="tamqpclient"),
    _rule("messaging", "STOMP/ActiveMQ", unit_re=(r"stomp\w*", r"activemq\w*"),
          classes="tstompclient"),
    _rule("messaging", "Kafka", unit_re=(r"kafka\w*",)),
    _rule("messaging", "ZeroMQ", unit_re=(r"zmq\w*", r"nanomsg\w*"),
          classes="tzmqcontext"),
    _rule("messaging", "IBM MQ", unit_re=(r"mqic\w*", r"wmq\w*"),
          units="mqseries"),
    _rule("messaging", "MSMQ", unit_re=(r"msmq\w*",)),
    # COM / DCOM
    _rule("com-ole", "COM/OLE",
          units="comobj activex oleauto ole2 olectrls axctrls olectnrs "
                "oleserver comserv winapi.activex system.win.comobj "
                "system.win.comserv vcl.olectrls vcl.axctrls",
          unit_re=(r"[a-z0-9]+_tlb", r"(?:excel|word|outlook|powerpoint|"
                   r"office|access)\d{2,4}"),
          classes="toleobject tolecontainer tolecontrol toleserver "
                  "tautoobject ttypedcomobject tautoobjectfactory "
                  "tcomobjectfactory",
          class_re=(r"t(?:excel|word|outlook|powerpoint)"
                    r"(?:application|workbook|worksheet|worksheets|document)",),
          idents="createoleobject getactiveoleobject createcomobject "
                 "coinitialize coinitializeex cocreateinstance"),
    _rule("dcom", "DCOM", units="mconnect objbrkr dcomcnct "
          "datasnap.win.mconnect", classes="tdcomconnection",
          idents="createremotecomobject cocreateinstanceex"),
    # LDAP
    _rule("ldap", "Windows LDAP", units="winldap winapi.winldap ldapapi",
          idents="ldap_init ldap_open ldap_bind_s ldap_search_s"),
    _rule("ldap", "ADSI", units="activeds adshlp",
          idents="adsopenobject adsgetobject"),
    # Serial ports
    _rule("serial-port", "ComPort Library",
          unit_re=(r"cport\w*",), classes="tcomport tcomdatapacket "
          "tcomterminal"),
    _rule("serial-port", "serial (FPC)", units="serial lazserial",
          classes="tlazserial"),
    # Services
    _rule("windows-service", "TService",
          units="svcmgr vcl.svcmgr",
          classes="tservice tserviceapplication tservicethread "
                  "tserviceapplicationex"),
    _rule("windows-service", "Service Control Manager",
          units="winsvc winapi.winsvc",
          idents="openscmanager openscmanagera openscmanagerw "
                 "startservicectrldispatcher registerservicectrlhandler"),
    _rule("windows-service", "FPC daemon", units="daemonapp lazdaemonapp",
          classes="tcustomdaemon tdaemon tdaemonapplication tdaemonmapper"),
    # Scheduling
    _rule("scheduled-job", "Task Scheduler", units="taskschd taskscheduler "
          "mstask"),
    # Printing
    _rule("printing", "Printers",
          units="printers vcl.printers winspool winapi.winspool printdlg "
                "osprinters",
          classes="tprinter tprintdialog tprintersetupdialog",
          idents="openprinter enumprinters getdefaultprinter startdocprinter"),
    # File exchange
    _rule("file-exchange", "Directory watcher",
          idents="findfirstchangenotification readdirectorychangesw"),
    # Reporting
    _rule("reporting", "QuickReport",
          unit_re=(r"quickrpt", r"qr(?!code|cod|gen|enc|dec|scan)[a-z]\w*"),
          classes="tquickrep", class_re=(r"tqr(?!code)[a-z]\w*",)),
    _rule("reporting", "FastReport", unit_re=(r"frx[a-z]\w*",),
          class_re=(r"tfrx\w+",)),
    _rule("reporting", "ReportBuilder", unit_re=(r"pp(?:class|db|rpt\w*|"
          r"viewr|prnabl|ctrls|comm|types|report|bde|dbpipe|cache|desig|"
          r"dsgnr)\w*",), class_re=(r"tpp(?:report|dbpipeline|label|"
          r"memo|detailband|dbtext)\w*",)),
    _rule("reporting", "Rave", unit_re=(r"rv(?:class|define|cs\w*|proj|"
          r"data\w*|tool|util|ld\w*|std|db\w*|custom|sys|render\w*|"
          r"device\w*)",), class_re=(r"trv(?:project|system|"
          r"datasetconnection)\w*",)),
    _rule("reporting", "Crystal Reports",
          units="crpe32 ucrpe32 crpe ucrpe", class_re=(r"tcrpe\w*",)),
    _rule("reporting", "LazReport", unit_re=(r"lr_\w+", r"lazreport\w*"),
          classes="tfrreport tfrdbdataset"),
)

# Dispatch indexes (built once; all keys lower-case).
CLASS_RULES: dict[str, list[IntegrationRule]] = {}
UNIT_RULES: tuple[IntegrationRule, ...] = INTEGRATION_RULES
IDENT_RULES: dict[str, list[IntegrationRule]] = {}
for _r in INTEGRATION_RULES:
    for _name in _r.classes:
        CLASS_RULES.setdefault(_name, []).append(_r)
    for _name in _r.idents:
        IDENT_RULES.setdefault(_name, []).append(_r)
del _r, _name


# --------------------------------------------------------------------------
# URL hosts that are namespaces, not endpoints
# --------------------------------------------------------------------------

_IGNORED_HOST_SUFFIXES = (
    "w3.org", "xmlsoap.org", "schemas.microsoft.com", "purl.org",
    "ns.adobe.com", "openxmlformats.org", "xmlns.com", "oasis-open.org",
    "schemas.openxmlformats.org", "tempuri.org",
)


def ignored_url_host(host: str) -> bool:
    """True for XML-namespace style hosts (``www.w3.org`` ...)."""

    low = host.lower().split(":", 1)[0]
    return any(low == s or low.endswith("." + s)
               for s in _IGNORED_HOST_SUFFIXES)


# --------------------------------------------------------------------------
# Runtime binaries
# --------------------------------------------------------------------------

#: OS-provided DLLs; reporting them as runtime dependencies would only add
#: "unresolved" noise (they are never shipped in an application tree).
SYSTEM_DLLS = frozenset({
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll", "shell32.dll",
    "ole32.dll", "oleaut32.dll", "comctl32.dll", "comdlg32.dll",
    "wsock32.dll", "ws2_32.dll", "winmm.dll", "shlwapi.dll", "version.dll",
    "wininet.dll", "winspool.drv", "urlmon.dll", "msvcrt.dll", "ntdll.dll",
    "imm32.dll", "crypt32.dll", "secur32.dll", "netapi32.dll", "psapi.dll",
    "iphlpapi.dll", "wintrust.dll", "mpr.dll", "setupapi.dll", "rpcrt4.dll",
    "winhttp.dll", "uxtheme.dll", "dwmapi.dll", "gdiplus.dll", "shfolder.dll",
    "userenv.dll", "wtsapi32.dll", "mapi32.dll", "wldap32.dll",
    "libc.so.6", "libdl.so.2", "libpthread.so.0", "libc.so", "libm.so.6",
})

#: ``(pattern, client)`` - database client libraries by file name.
DB_CLIENT_LIBRARIES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.I), label) for p, label in (
        (r"oci\.dll|ociw32\.dll|oraclient\d*\.dll|libclntsh\.so[\d.]*"
         r"|orannzsbb\d*\.dll", "Oracle"),
        (r"libpq(?:\.dll|\.so[\d.]*|\.dylib)", "PostgreSQL"),
        (r"fbclient\.dll|libfbclient\.\w+[\d.]*|fbembed\.dll", "Firebird"),
        (r"gds32\.dll|ibclient\d*\.dll", "InterBase"),
        (r"sqlite3\.dll|libsqlite3[\w.]*|sqlite3_\w+\.dll", "SQLite"),
        (r"libmysql\.dll|libmariadb[\w.]*|libmysqlclient[\w.]*"
         r"|libmysqld\.dll", "MySQL"),
        (r"sqlncli\d*\.dll|msodbcsql\d*\.dll|ntwdblib\.dll|odbc32\.dll"
         r"|sqloledb\.dll", "SQL Server"),
        (r"db2cli\.dll", "DB2"),
    )
)

#: FireDAC ``DriverID`` / ``FireDAC.Phys.<x>`` prefix → client library.
FIREDAC_DRIVER_CLIENT: dict[str, str] = {
    "ora": "oci.dll",
    "pg": "libpq.dll",
    "mysql": "libmysql.dll",
    "sqlite": "sqlite3.dll",
    "fb": "fbclient.dll",
    "ib": "gds32.dll",
}

#: ``metadata`` database technology → implied client library.
TECH_CLIENT: dict[str, str] = {
    "Oracle (SQLdb)": "oci.dll",
    "PostgreSQL (SQLdb)": "libpq.dll",
    "SQLite (SQLdb)": "sqlite3.dll",
    "InterBase/Firebird": "fbclient.dll",
    "MyDAC (MySQL)": "libmysql.dll",
}
