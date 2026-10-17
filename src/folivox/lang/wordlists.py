"""Frequent function words and telltale letters of the Latin-script languages, for telling a whole book's language.

Same idea as the two steps of statistical detectors (Lingua, CLD): letters that exist in few languages narrow the
field, then the counts of very frequent words decide. A book is tens of thousands of letters, so a few dozen
function words per language are enough; short strings are not the goal (see ``detect.latin_lang`` for those).
"""

from __future__ import annotations

# Function words, lowercase. A word may appear in several lists (de, la, in): the language with the most hits wins.
WORDS = {
    "en": "the and of to a in that is was he it for with his as had you not but at on her she they",
    "de": "der die und das ist nicht ich sie es zu den mit sich auf ein eine dem war er auch",
    "fr": "le la les et des est une un que il pas du dans qui elle ne se au je sur avec",
    "es": "el la que de y los las en un una del se por con no su para es lo como pero",
    "it": "il la che di e non un una per del gli le si è da con ho lo ma sono della",
    "pt": "o a os as de do da dos das em no na nos nas um uma que e não com para por se mais como mas foi ao é "
          "são está ele ela eu isso muito já também ou seu sua",
    "nl": "de het een en van in is dat op te zijn met voor niet aan er maar om ook als dan bij nog door ze hij "
          "zij wat uit naar",
    "pl": "i w nie na się z do to że jest jak co ale po tak za od przez już czy tylko być jego jej który która "
          "które był była było są oraz",
    "cs": "a v se na je že s z do to o jako ale byl byla bylo jsou si by ke pro tak už od po jeho její který "
          "která které nebo když",
    "sk": "a v sa na je že s z do to o ako ale bol bola bolo sú si by ku pre tak už od po jeho jej ktorý ktorá "
          "ktoré alebo keď",
    "sl": "in v je na se da z za so ki ne kot ali bil bila bilo sta pa ter pri iz do po tudi lahko kar",
    "hr": "i u je da se na za s od ne su sam smo bio bila bilo koji koja koje što kao ali iz do po ili",
    "ro": "și în de la a o un pe cu că nu este pentru care din mai sunt era fost dar sau ce se să au al lui",
    "hu": "a az és hogy nem is egy meg el de ez van volt csak már még ha vagy mint át ki fel",
    "tr": "ve bir bu da de için ile ne çok gibi daha ama ben sen o var yok olarak kadar sonra değil mi mı",
    "sv": "och i att det som en är av för på med till den har inte om ett jag var han de vi men från",
    "da": "og i at det som en er af for på med til den har ikke om et jeg var han de vi men fra hvad efter "
          "mig dig sig være været blev bliver kunne skulle nogle noget",
    "nb": "og i at det som en er av for på med til den har ikke om et jeg var han de vi men fra hva etter "
          "meg deg seg være vært ble blir kunne skulle noen noe å",
    "fi": "ja on ei että se oli hän mutta kun niin ole myös vain sitä kuin tai mitä jos",
    "ca": "el la i de que a en un una és per amb no al les els del es com més però",
    "lt": "ir yra kad tai su ne iš į kaip bet jis ji buvo apie",
    "lv": "un ir ka tas par no uz ar nav bet viņš viņa bija kā",
    "et": "ja on ei et see oli ta kui aga ka või mis",
    "is": "og að er í á ekki það sem hann var en til með",
    "vi": "và của là có không được cho một những trong các này để với đã",
    "id": "yang dan di ke dari ini itu dengan untuk tidak pada adalah akan juga",
    "sw": "na ya wa kwa ni katika za la kuwa hii huo",
    "sq": "dhe e të në që një për me nga është ka si por ishte",
}

# Letters that mark a language among the Latin ones (an accent shared by many, like é, is left out)
LETTERS = {
    "de": "ßäöü", "fr": "èêëàâçîïôùûœ", "es": "ñ¿¡", "it": "ìòù", "pt": "ãõç", "pl": "ąćęłńśźż", "cs": "ěřůťďň",
    "sk": "ĺľŕôäň", "sl": "čšž", "hr": "čćđšž", "ro": "ăâîșțşţ", "hu": "őű", "tr": "ğışİ", "sv": "åäö",
    "da": "æøå", "nb": "æøå", "fi": "äö", "ca": "ŀ·", "lt": "ąčęėįšųūž", "lv": "āēģīķļņū", "et": "õäöü",
    "is": "þð", "vi": "ăơưđạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữự", "sq": "ë", "sw": "",
}
LETTER_WEIGHT = 0.5
