"""Русский каталог сообщений интерфейса (English → русский)."""

MESSAGES = {
    # cli: general
    "Folivox — turn e-books (FB2, EPUB, DOCX, PDF, TXT) into m4b audiobooks, locally.":
        "Folivox — локальная озвучка книг (FB2, EPUB, DOCX, PDF, TXT) в аудиокнигу m4b.",
    "{h} h {m:02d} min": "{h} ч {m:02d} мин",
    "{m} min {s:02d} s": "{m} мин {s:02d} с",
    "{s:.1f} s": "{s:.1f} с",
    "File not found:": "Файл не найден:",
    "Show the version": "Показать версию",
    "Error:": "Ошибка:",
    "Done:": "Готово:",
    "chars": "симв.",
    "ch.": "гл.",
    "f": "ж",
    "m": "м",
    "no": "нет",
    "yes ({kb} KB)": "есть ({kb} КБ)",
    # inspect
    "Show the book structure, chapters and estimated audio length.":
        "Показать структуру книги, главы и оценку длительности аудио.",
    "Book file": "Файл книги",
    "Chapter split depth (1 — top level only)": "Глубина разбиения на главы (1 — только верхний уровень)",
    "Book language (default: from metadata / detected)": "Язык книги (по умолчанию — из метаданных или по тексту)",
    "Show the beginning of every chapter": "Показать начало текста каждой главы",
    "Title": "Название",
    "Author": "Автор",
    "Language": "Язык",
    "Format": "Формат",
    "Year": "Год",
    "Cover": "Обложка",
    "Size": "Объём",
    "{chars} characters, {words} words": "{chars} символов, {words} слов",
    "Audio (estimate)": "Аудио (оценка)",
    "(untitled)": "(без названия)",
    "Audiobook chapters ({n})": "Главы аудиокниги ({n})",
    "Chapter": "Глава",
    "Characters": "Символов",
    "≈ Time": "≈ Время",
    "Beginning": "Начало",
    # render
    "Render a book into an audiobook (m4b with chapters and cover).":
        "Озвучить книгу в аудиокнигу (m4b с главами и обложкой).",
    "Book file (FB2, EPUB, DOCX, PDF, TXT)": "Файл книги (FB2, EPUB, DOCX, PDF, TXT)",
    "Voice id from the catalog (folivox voices) or a WAV/FLAC file with 6–15 s of clean speech":
        "Голос из каталога (folivox voices) или файл WAV/FLAC 6–15 с чистой речи",
    "by book language": "по языку книги",
    "Transcript of the sample (text or .txt). Default: .txt next to the sample, else Whisper":
        "Расшифровка образца (текст или .txt). По умолчанию — .txt рядом с образцом или Whisper",
    "Output .m4b (or a folder with --mp3)": "Итоговый .m4b (или папка для --mp3)",
    "Book language: ru en de fr es it zh ja ko (default: from metadata / detected)":
        "Язык книги: ru en de fr es it zh ja ko (по умолчанию — из метаданных или по тексту)",
    "Which chapters: 1-3,5": "Какие главы: 1-3,5",
    "Only the first N characters of each chapter": "Только первые N символов каждой главы (проба)",
    "MP3 per chapter instead of one m4b": "MP3 по главам вместо одного m4b",
    "Cache folder (default <output>.folivox)": "Папка кэша (по умолчанию <output>.folivox)",
    "Chapter split depth": "Глубина разбиения на главы",
    "Longest fragment sent to the model": "Максимальная длина фрагмента для модели",
    "Russian: none | yo (restore ё) | all (stress marks, experimental)":
        "Для русского: none | yo (только ё) | all (ударения, эксперимент)",
    "Speaking rate": "Темп речи",
    "Check every fragment with speech recognition": "Проверять каждый фрагмент распознаванием речи",
    "Max takes per fragment when QA finds a mismatch": "Максимум дублей на фрагмент при ошибке распознавания",
    "TTS provider (folivox providers)": "Провайдер синтеза речи (folivox providers)",
    "Speech recognition provider for QA": "Провайдер распознавания речи для проверки",
    "CosyVoice LLM weights: rl (fewer text errors) | base": "Веса LLM CosyVoice: rl (меньше ошибок в тексте) | base",
    "PyTorch CPU threads": "Потоков CPU для PyTorch",
    "CosyVoice 3 weights folder (downloaded otherwise)": "Папка с весами CosyVoice 3 (иначе скачаются)",
    "AAC bitrate": "Битрейт AAC",
    "Print every fragment": "Печатать каждый фрагмент",
    "The voice sample is in {v}, the book in {b}: the accent may carry over.":
        "Образец голоса на языке {v}, книга — {b}: акцент может перейти в озвучку.",
    "unknown author": "автор неизвестен",
    "estimated audio": "оценка аудио",
    "Stopped. Progress is saved — run the same command again to continue.":
        "Остановлено. Прогресс сохранён — запустите ту же команду, чтобы продолжить.",
    "Synthesis: {synth} for {audio} of audio, RTF {rtf:.2f}": "Синтез: {synth} на {audio} аудио, RTF {rtf:.2f}",
    "Fragments: {total}, left {pending}; text {chars} chars (done {done})":
        "Фрагментов: {total}, осталось {pending}; текст {chars} симв. (готово {done})",
    "Rendering": "Озвучка",
    "RTF {rtf:.2f} · audio {audio}": "RTF {rtf:.2f} · аудио {audio}",
    " · retakes {n}": " · перезаписей {n}",
    "Voice {v!r} not found.": "Голос {v!r} не найден.",
    "Catalog: {ids}. Or give a WAV/FLAC path.": "В каталоге: {ids}. Или укажите путь к WAV/FLAC.",
    # voices
    "Voice catalog": "Каталог голосов",
    "List available voices.": "Показать доступные голоса.",
    "Only voices in this language": "Только голоса на этом языке",
    "Voices": "Голоса",
    "Name": "Название",
    "Sex": "Пол",
    "Length": "Длит.",
    "License": "Лицензия",
    "Where": "Где",
    "bundled": "встроенный",
    "mine": "мой",
    "* default voice. Your voices: {path}": "* голос по умолчанию. Свои голоса: {path}",
    "Add your own voice to the catalog (stays on this computer).":
        "Добавить свой голос в каталог (хранится только на этом компьютере).",
    "Id: latin letters, digits, - and _": "Имя: латиница, цифры, - и _",
    "WAV/FLAC/MP3 sample, 6–15 s": "WAV/FLAC/MP3 с образцом 6–15 с",
    "Transcript (text or .txt); otherwise Whisper": "Расшифровка (текст или .txt); иначе Whisper",
    "Human-readable name": "Человекочитаемое название",
    "Language of the sample": "Язык образца",
    "License / origin of the sample": "Лицензия/происхождение образца",
    "Overwrite an existing voice": "Перезаписать существующий",
    "Voice added:": "Добавлен голос",
    "Remove one of your voices from the catalog.": "Удалить свой голос из каталога.",
    "Removed {id}": "Удалён {id}",
    "Generate a reference voice with a voice generator, pick the best take by speech recognition.":
        "Создать опорный голос генератором голосов и выбрать лучший дубль по распознаванию речи.",
    "Id of the new voice": "Имя нового голоса",
    "Voice description for a design generator, e.g. \"calm native Russian female audiobook narrator\"":
        "Описание голоса для генератора (лучше по-английски), например "
        "\"calm native Russian female audiobook narrator\"",
    "Preset speaker for a preset generator": "Готовый диктор для генератора с пресетами",
    "Text to read (repeatable); default: built-in safe texts":
        "Текст для чтения (можно несколько раз); по умолчанию — встроенные «безопасные» тексты",
    "Takes per text": "Дублей на текст",
    "Voice generator provider": "Провайдер генерации голоса",
    "Folder to keep every take for listening": "Папка, куда сохранить все дубли для прослушивания",
    "Add the best take to the catalog": "Добавить лучший дубль в каталог",
    "--describe is required for {g}": "Для {g} нужен --describe",
    "--speaker is required for {g}: {s}": "Для {g} нужен --speaker: {s}",
    "No built-in texts for {lang}; pass --text": "Нет встроенных текстов для {lang}; укажите --text",
    "Generating {n} takes with {g}…": "Генерирую {n} дублей через {g}…",
    "take {i}/{n} ({s:.0f} s)": "дубль {i}/{n} ({s:.0f} с)",
    "Checking takes with speech recognition…": "Проверяю дубли распознаванием речи…",
    "File": "Файл",
    "Score": "Оценка",
    "Recognised": "Распознано",
    "All takes: {path}": "Все дубли: {path}",
    "Pick passages from a book that are safe for a voice generator to read (by a text LLM).":
        "Подобрать в книге фрагменты, безопасные для чтения генератором голоса (с помощью LLM).",
    "How many passages": "Сколько фрагментов",
    "Book language": "Язык книги",
    "Text LLM provider": "Провайдер текстовой LLM",
    "LLM model name": "Модель LLM",
    "Nothing suitable found.": "Подходящих фрагментов не нашлось.",
    # providers
    "List pluggable backends: TTS, speech recognition, voice generators, text LLMs.":
        "Показать подключаемые бэкенды: синтез речи, распознавание, генераторы голосов, текстовые LLM.",
    "Providers": "Провайдеры",
    "Kind": "Тип",
    "Description": "Описание",
    "Runs": "Где работает",
    "Needs": "Требует",
    "locally": "локально",
    "cloud API (your key)": "облачный API (ваш ключ)",
    "* selected. Config: {path}": "* выбран. Конфиг: {path}",
    # pipeline
    "Invalid chapter number: {part!r}": "Неверный номер главы: {part!r}",
    "The book has no chapters {spec!r} (there are {count})": "В книге нет глав {spec!r} (всего {count})",
    "Preparing text: {n} of {total} chapters": "Разметка текста: {n} из {total} глав",
    "Chapter “{title}” is not fully rendered — skipping": "Глава «{title}» озвучена не полностью — пропускаю",
    "Building chapter {n}: {title}": "Сборка главы {n}: {title}",
    "Nothing to assemble: no chapter is fully rendered": "Нечего собирать: ни одна глава не озвучена полностью",
    "Encoding {fmt}": "Кодирование {fmt}",
    "Loading speech recognition for QA ({name})": "Загрузка распознавания речи для проверки ({name})",
    "Loading TTS model ({name})": "Загрузка модели синтеза ({name})",
    "Model loaded in {s:.0f} s ({device})": "Модель загружена за {s:.0f} с ({device})",
    # voices / voice samples
    "Voice id: lowercase latin letters, digits, '-' and '_', up to 40 characters":
        "Имя голоса: латиница в нижнем регистре, цифры, «-» и «_», до 40 символов",
    "Voice {id!r} already exists (use --force)": "Голос {id!r} уже есть (используйте --force)",
    "No user voice {id!r}": "Пользовательского голоса {id!r} нет",
    "Voice file not found: {path}": "Файл голоса не найден: {path}",
    "Cannot read audio {path}: {error}": "Не удалось прочитать аудио {path}: {error}",
    "The voice sample is too short ({d:.1f} s); 6–15 s is needed.":
        "Образец голоса слишком короткий ({d:.1f} с), нужно 6–15 с.",
    "The voice sample is too long ({d:.1f} s); trim it to 6–15 s.":
        "Образец голоса слишком длинный ({d:.1f} с), обрежьте до 6–15 с.",
    "A transcript of the voice sample is needed: --voice-text \"…\" or a .txt next to it":
        "Нужна расшифровка образца голоса: --voice-text \"…\" или файл .txt рядом с ним",
    "The voice sample is {d:.1f} s long; 6–15 s of clean speech works best.":
        "Образец голоса длится {d:.1f} с; лучше всего работает 6–15 с чистой речи.",
    # readers, audio, weights
    "Unsupported format: {name} (supported: {formats})": "Неподдерживаемый формат: {name} (поддерживаются {formats})",
    "Cannot parse FB2: {path}": "Не удалось разобрать FB2: {path}",
    "ffmpeg not found. Install it: macOS — brew install ffmpeg; Windows — winget install ffmpeg; "
    "Linux — apt install ffmpeg":
        "ffmpeg не найден. Установите: macOS — brew install ffmpeg; Windows — winget install ffmpeg; "
        "Linux — apt install ffmpeg",
    "ffmpeg failed:": "ffmpeg завершился с ошибкой:",
    "{path} has no complete set of CosyVoice 3 weights (needed: {files})":
        "В {path} нет полного набора весов CosyVoice 3 (нужны: {files})",
    "Weights not found in {path}": "Веса не найдены в {path}",
    "Downloading {name} (~2 GB)…": "Скачиваю {name} (~2 ГБ)…",
    "Downloading CosyVoice 3 weights (~4.5 GB) from huggingface.co/{repo} to {path}…":
        "Скачиваю веса CosyVoice 3 (~4.5 ГБ) из huggingface.co/{repo} в {path}…",
    "Weights download incomplete: {path}": "Загрузка весов не завершена: {path}",
}
