from __future__ import annotations

from typing import Any
import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QTabWidget,
    QTableWidget,
    QWidget,
)


LANGUAGES: tuple[tuple[str, str], ...] = (
    ("zh_CN", "中文"),
    ("en", "English"),
    ("ja", "日本語"),
    ("es", "Español"),
    ("it", "Italiano"),
    ("is", "Íslenska"),
    ("la", "Latina"),
)

_LANGUAGE_CODES = {code for code, _label in LANGUAGES}
_CURRENT_LANGUAGE = "zh_CN"


def _row(
    zh: str,
    en: str,
    ja: str,
    es: str,
    it: str,
    is_: str,
    la: str,
) -> dict[str, str]:
    return {
        "zh_CN": zh,
        "en": en,
        "ja": ja,
        "es": es,
        "it": it,
        "is": is_,
        "la": la,
    }


# Source text is deliberately kept in the table. The reverse index means a
# live UI can move from English -> Japanese -> Spanish without rebuilding the
# whole application or remembering the original Chinese string on each widget.
_TRANSLATIONS: dict[str, dict[str, str]] = {
    "主页": _row("主页", "Home", "ホーム", "Inicio", "Home", "Heim", "Pagina Principalis"),
    "工作台": _row("工作台", "Workbench", "ワークベンチ", "Mesa de trabajo", "Banco di lavoro", "Vinnuborð", "Officina"),
    "小工具": _row("小工具", "Utilities", "ツール", "Herramientas", "Strumenti", "Verkfæri", "Instrumenta"),
    "控制台": _row("控制台", "Console", "コンソール", "Consola", "Console", "Stjórnborð", "Consola"),
    "设置": _row("设置", "Settings", "設定", "Ajustes", "Impostazioni", "Stillingar", "Configurationes"),
    "外观与语言": _row("外观与语言", "Appearance & Language", "外観と言語", "Apariencia e idioma", "Aspetto e lingua", "Útlit og tungumál", "Aspectus et Lingua"),
    "主题": _row("主题", "Theme", "テーマ", "Tema", "Tema", "Þema", "Thema"),
    "深色": _row("深色", "Dark", "ダーク", "Oscuro", "Scuro", "Dökkt", "Obscurum"),
    "浅色": _row("浅色", "Light", "ライト", "Claro", "Chiaro", "Ljóst", "Clarum"),
    "语言": _row("语言", "Language", "言語", "Idioma", "Lingua", "Tungumál", "Lingua"),
    "显示快捷工具栏": _row("显示快捷工具栏", "Show quick toolbar", "クイックツールバーを表示", "Mostrar barra rápida", "Mostra barra rapida", "Sýna flýtiverkfærastiku", "Ostende instrumenta celeria"),
    "工作台模式": _row("工作台模式", "Workbench mode", "ワークベンチモード", "Modo de trabajo", "Modalità banco", "Vinnuborðshamur", "Modus officinae"),
    "简单模式（拼图模式）": _row("简单模式（拼图模式）", "Simple mode (Puzzle)", "シンプルモード（パズル）", "Modo simple (puzle)", "Modalità semplice (puzzle)", "Einfaldur hamur (púsl)", "Modus simplex (tesserae)"),
    "复杂模式（节点与连线）": _row("复杂模式（节点与连线）", "Complex mode (Nodes & wires)", "複雑モード（ノードと接続）", "Modo complejo (nodos y enlaces)", "Modalità complessa (nodi e collegamenti)", "Flókinn hamur (hnútar og tengingar)", "Modus complexus (nodi et nexus)"),
    "热键": _row("热键", "Hotkeys", "ホットキー", "Atajos", "Tasti rapidi", "Flýtilyklar", "Claves Celeres"),
    "快捷建立模板": _row("快捷建立模板", "Quick template capture", "クイックテンプレート作成", "Crear plantilla rápida", "Crea modello rapido", "Flýtisniðmát", "Exemplar celeriter crea"),
    "视觉识别系统视角": _row("视觉识别系统视角", "Recognition viewport", "認識システムビュー", "Vista del reconocimiento", "Vista riconoscimento", "Sjónarhorn greiningar", "Prospectus recognitionis"),
    "录制": _row("录制", "Record", "記録", "Grabar", "Registra", "Taka upp", "Registra"),
    "识别引擎": _row("识别引擎", "Recognition engine", "認識エンジン", "Motor de reconocimiento", "Motore di riconoscimento", "Greiningarvél", "Machina recognitionis"),
    "识别后端": _row("识别后端", "Recognition backend", "認識バックエンド", "Backend de reconocimiento", "Backend riconoscimento", "Greiningarbakendi", "Pars posterior recognitionis"),
    "最大识别帧率": _row("最大识别帧率", "Maximum recognition FPS", "最大認識FPS", "FPS máximo de reconocimiento", "FPS massimo riconoscimento", "Hámarks greiningar-FPS", "Maxima frequentia recognitionis"),
    "排除视觉识别视角窗口": _row("排除视觉识别视角窗口", "Exclude recognition viewport window", "認識ビューウィンドウを除外", "Excluir ventana de reconocimiento", "Escludi finestra riconoscimento", "Útiloka greiningarglugga", "Fenestra recognitionis excludatur"),
    "显示时间戳": _row("显示时间戳", "Show timestamps", "タイムスタンプを表示", "Mostrar marcas de tiempo", "Mostra timestamp", "Sýna tímastimpla", "Tempora ostende"),
    "允许使用 !command 执行系统命令": _row("允许使用 !command 执行系统命令", "Allow !command system commands", "!command によるシステムコマンドを許可", "Permitir comandos del sistema con !command", "Consenti comandi di sistema con !command", "Leyfa kerfisskipanir með !command", "Permitte mandata systematis per !command"),
    "最大控制台行数": _row("最大控制台行数", "Maximum console lines", "コンソール最大行数", "Máximo de líneas de consola", "Righe massime console", "Hámarksfjöldi lína í stjórnborði", "Maximae lineae consolae"),
    "数据与配置": _row("数据与配置", "Data & Configuration", "データと構成", "Datos y configuración", "Dati e configurazione", "Gögn og stillingar", "Data et Configurationes"),
    "打开数据文件夹": _row("打开数据文件夹", "Open data folder", "データフォルダーを開く", "Abrir carpeta de datos", "Apri cartella dati", "Opna gagnamöppu", "Aperi directorium datorum"),
    "恢复默认设置": _row("恢复默认设置", "Restore defaults", "既定値に戻す", "Restaurar valores predeterminados", "Ripristina predefiniti", "Endurheimta sjálfgefið", "Praedefinita restitue"),
    "保存": _row("保存", "Save", "保存", "Guardar", "Salva", "Vista", "Serva"),
    "导入": _row("导入", "Import", "インポート", "Importar", "Importa", "Flytja inn", "Importa"),
    "导出": _row("导出", "Export", "エクスポート", "Exportar", "Esporta", "Flytja út", "Exporta"),
    "切换项目": _row("切换项目", "Switch project", "プロジェクト切替", "Cambiar proyecto", "Cambia progetto", "Skipta um verkefni", "Projectum muta"),
    "关闭项目": _row("关闭项目", "Close project", "プロジェクトを閉じる", "Cerrar proyecto", "Chiudi progetto", "Loka verkefni", "Projectum claude"),
    "打开项目文件夹": _row("打开项目文件夹", "Open project folder", "プロジェクトフォルダーを開く", "Abrir carpeta del proyecto", "Apri cartella progetto", "Opna verkefnismöppu", "Aperi directorium projecti"),
    "重置视图": _row("重置视图", "Reset view", "表示をリセット", "Restablecer vista", "Reimposta vista", "Endurstilla sýn", "Prospectum restitue"),
    "运行": _row("运行", "Run", "実行", "Ejecutar", "Esegui", "Keyra", "Exsequere"),
    "停止": _row("停止", "Stop", "停止", "Detener", "Ferma", "Stöðva", "Siste"),
    "模块库": _row("模块库", "Module library", "モジュールライブラリ", "Biblioteca de módulos", "Libreria moduli", "Einingasafn", "Bibliotheca modulorum"),
    "概览": _row("概览", "Overview", "概要", "Resumen", "Panoramica", "Yfirlit", "Conspectus"),
    "感知": _row("感知", "Sensing", "感知", "Percepción", "Rilevamento", "Skynjun", "Sensus"),
    "动作": _row("动作", "Actions", "アクション", "Acciones", "Azioni", "Aðgerðir", "Actiones"),
    "逻辑": _row("逻辑", "Logic", "ロジック", "Lógica", "Logica", "Rökfræði", "Logica"),
    "数据": _row("数据", "Data", "データ", "Datos", "Dati", "Gögn", "Data"),
    "调试": _row("调试", "Debug", "デバッグ", "Depuración", "Debug", "Kembing", "Diagnostica"),
    "全局设置": _row("全局设置", "Global settings", "グローバル設定", "Ajustes globales", "Impostazioni globali", "Víðværar stillingar", "Configurationes globales"),
    "自定义模块": _row("自定义模块", "Custom modules", "カスタムモジュール", "Módulos personalizados", "Moduli personalizzati", "Sérsniðnar einingar", "Moduli consuetudinales"),
    "事件": _row("事件", "Events", "イベント", "Eventos", "Eventi", "Atburðir", "Eventus"),
    "扫描模板（坐标输出）": _row("扫描模板（坐标输出）", "Scan template (coordinate output)", "テンプレート走査（座標出力）", "Escanear plantilla (salida de coordenadas)", "Scansiona modello (uscita coordinate)", "Skanna sniðmát (hnit úttak)", "Exemplar explora (coordinatae)"),
    "模板计数（单数字输出）": _row("模板计数（单数字输出）", "Template count (number output)", "テンプレート数（数値出力）", "Contar plantilla (salida numérica)", "Conteggio modello (uscita numero)", "Telja sniðmát (töluúttak)", "Exemplaria numera (numerus)"),
    "锁定模板（坐标输出）": _row("锁定模板（坐标输出）", "Lock template (coordinate output)", "テンプレート追跡（座標出力）", "Bloquear plantilla (salida de coordenadas)", "Blocca modello (uscita coordinate)", "Læsa sniðmáti (hnit úttak)", "Exemplar fige (coordinatae)"),
    "持续扫描模板直到发现（坐标输出）": _row("持续扫描模板直到发现（坐标输出）", "Scan until found (coordinate output)", "発見まで連続走査（座標出力）", "Escanear hasta encontrar (coordenadas)", "Scansiona fino al rilevamento (coordinate)", "Skanna þar til finnst (hnit)", "Explora donec inveniatur (coordinatae)"),
    "移至": _row("移至", "Move to", "移動", "Mover a", "Sposta a", "Færa til", "Move ad"),
    "拖动": _row("拖动", "Drag", "ドラッグ", "Arrastrar", "Trascina", "Draga", "Trahe"),
    "点击": _row("点击", "Click", "クリック", "Clic", "Clic", "Smella", "Preme"),
    "键盘输入": _row("键盘输入", "Keyboard input", "キーボード入力", "Entrada de teclado", "Input tastiera", "Lyklaborðsinntak", "Ingressus claviaturae"),
    "启动程序": _row("启动程序", "Launch program", "プログラム起動", "Iniciar programa", "Avvia programma", "Ræsa forrit", "Programma inicia"),
    "延时等待": _row("延时等待", "Delay", "待機", "Espera", "Attesa", "Bið", "Mora"),
    "ROI": _row("ROI", "ROI", "ROI", "ROI", "ROI", "ROI", "ROI"),
    "循环": _row("循环", "Loop", "ループ", "Bucle", "Ciclo", "Lykkja", "Iteratio"),
    "循环…直到…": _row("循环…直到…", "Loop…until…", "ループ…まで…", "Bucle…hasta…", "Ciclo…finché…", "Lykkja…þar til…", "Itera…donec…"),
    "OR（任一满足）": _row("OR（任一满足）", "OR (either true)", "OR（いずれか）", "OR (cualquiera)", "OR (uno qualsiasi)", "OR (annað hvort)", "OR (alterutrum)"),
    "NOR（均不满足）": _row("NOR（均不满足）", "NOR (neither true)", "NOR（どちらも偽）", "NOR (ninguno)", "NOR (nessuno)", "NOR (hvorugt)", "NOR (neutrum)"),
    "AND（同时满足）": _row("AND（同时满足）", "AND (both true)", "AND（両方）", "AND (ambos)", "AND (entrambi)", "AND (bæði)", "AND (ambo)"),
    "固定坐标（坐标输出）": _row("固定坐标（坐标输出）", "Fixed coordinate (coordinate output)", "固定座標（座標出力）", "Coordenada fija (salida)", "Coordinata fissa (uscita)", "Fast hnit (hnit úttak)", "Coordinata fixa (exitus)"),
    "坐标修改（坐标输出）": _row("坐标修改（坐标输出）", "Modify coordinate (coordinate output)", "座標変更（座標出力）", "Modificar coordenada (salida)", "Modifica coordinata (uscita)", "Breyta hniti (hnit úttak)", "Coordinatam muta (exitus)"),
    "检测输入": _row("检测输入", "Inspect input", "入力を検査", "Inspeccionar entrada", "Ispeziona input", "Skoða inntak", "Ingressum inspice"),
    "仅识别锚点": _row("仅识别锚点", "Restrict to anchor ROI", "アンカーROIのみ認識", "Reconocer solo ROI del ancla", "Riconosci solo ROI ancorata", "Greina aðeins akkerissvæði", "Solum ROI ancorae agnosce"),
    "时钟": _row("时钟", "Clock", "タイマー", "Reloj", "Timer", "Klukka", "Horologium"),
    "起始": _row("起始", "Start", "開始", "Inicio", "Avvio", "Byrjun", "Initium"),
    "新建项目": _row("新建项目", "New project", "新規プロジェクト", "Nuevo proyecto", "Nuovo progetto", "Nýtt verkefni", "Projectum novum"),
    "导入项目": _row("导入项目", "Import project", "プロジェクトをインポート", "Importar proyecto", "Importa progetto", "Flytja inn verkefni", "Projectum importa"),
    "打开选中项目": _row("打开选中项目", "Open selected project", "選択したプロジェクトを開く", "Abrir proyecto seleccionado", "Apri progetto selezionato", "Opna valið verkefni", "Projectum selectum aperi"),
    "删除项目": _row("删除项目", "Delete project", "プロジェクトを削除", "Eliminar proyecto", "Elimina progetto", "Eyða verkefni", "Projectum dele"),
    "还没有打开项目": _row("还没有打开项目", "No project is open", "プロジェクトが開かれていません", "No hay un proyecto abierto", "Nessun progetto aperto", "Ekkert verkefni er opið", "Nullum projectum apertum est"),
    "鼠标坐标监视器": _row("鼠标坐标监视器", "Mouse coordinate monitor", "マウス座標モニター", "Monitor de coordenadas del ratón", "Monitor coordinate mouse", "Músarhnitamælir", "Monitor coordinatarum muris"),
    "启动": _row("启动", "Start", "開始", "Iniciar", "Avvia", "Ræsa", "Inicia"),
    "坐标系": _row("坐标系", "Coordinate system", "座標系", "Sistema de coordenadas", "Sistema di coordinate", "Hnitakerfi", "Systema coordinatarum"),
    "全屏坐标（默认）": _row("全屏坐标（默认）", "Fullscreen coordinates (default)", "全画面座標（既定）", "Coordenadas de pantalla completa (pred.)", "Coordinate schermo intero (predef.)", "Hnit alls skjás (sjálfgefið)", "Coordinatae totius scrinii (praedef.)"),
    "刷新模板": _row("刷新模板", "Refresh templates", "テンプレート更新", "Actualizar plantillas", "Aggiorna modelli", "Endurnýja sniðmát", "Exemplaria renova"),
    "删除上一项": _row("删除上一项", "Delete last", "最後を削除", "Eliminar último", "Elimina ultimo", "Eyða síðasta", "Ultimum dele"),
    "清空": _row("清空", "Clear", "クリア", "Limpiar", "Svuota", "Hreinsa", "Purga"),
    "复制表格（Excel）": _row("复制表格（Excel）", "Copy table (Excel)", "表をコピー（Excel）", "Copiar tabla (Excel)", "Copia tabella (Excel)", "Afrita töflu (Excel)", "Tabulam copia (Excel)"),
    "导入自定义模块": _row("导入自定义模块", "Import custom module", "カスタムモジュールをインポート", "Importar módulo personalizado", "Importa modulo personalizzato", "Flytja inn sérsniðna einingu", "Modulum consuetudinalem importa"),
    "打开自定义模块文件夹": _row("打开自定义模块文件夹", "Open custom-module folder", "カスタムモジュールフォルダーを開く", "Abrir carpeta de módulos personalizados", "Apri cartella moduli personalizzati", "Opna möppu sérsniðinna eininga", "Aperi directorium modulorum consuetudinalium"),
    "打开文件位置": _row("打开文件位置", "Open file location", "ファイルの場所を開く", "Abrir ubicación del archivo", "Apri percorso file", "Opna skráarstað", "Locum fasciculi aperi"),
    "删除": _row("删除", "Delete", "削除", "Eliminar", "Elimina", "Eyða", "Dele"),
    "新建为新自定义模块": _row("新建为新自定义模块", "Create custom module", "カスタムモジュールとして作成", "Crear módulo personalizado", "Crea modulo personalizzato", "Búa til sérsniðna einingu", "Modulum consuetudinalem crea"),
}

# Language names should also be translatable in the combo box, though native
# names remain recognizable when the interface is switched.
_TRANSLATIONS.update(
    {
        "中文": _row("中文", "Chinese", "中国語", "Chino", "Cinese", "Kínverska", "Sinica"),
        "English": _row("English", "English", "英語", "Inglés", "Inglese", "Enska", "Anglica"),
        "日本語": _row("日本語", "Japanese", "日本語", "Japonés", "Giapponese", "Japanska", "Iaponica"),
        "Español": _row("Español", "Spanish", "スペイン語", "Español", "Spagnolo", "Spænska", "Hispanica"),
        "Italiano": _row("Italiano", "Italian", "イタリア語", "Italiano", "Italiano", "Ítalska", "Italica"),
        "Íslenska": _row("Íslenska", "Icelandic", "アイスランド語", "Islandés", "Islandese", "Íslenska", "Islandica"),
        "Latina": _row("Latina", "Latin", "ラテン語", "Latín", "Latino", "Latína", "Latina"),
    }
)


# Additional page-level strings. Keeping these in the same source-text table
# lets the event filter translate existing pages without replacing their files.
_TRANSLATIONS.update({
    "UVAF 的运行状态和常用入口会显示在这里。": _row("UVAF 的运行状态和常用入口会显示在这里。", "UVAF status and common entry points appear here.", "UVAF の状態と主要な入口を表示します。", "Aquí se muestran el estado de UVAF y los accesos habituales.", "Qui vengono mostrati lo stato di UVAF e gli accessi principali.", "Hér birtast staða UVAF og algengar flýtileiðir.", "Hic status UVAF et aditus usitati ostenduntur."),
    "当前状态": _row("当前状态", "Current status", "現在の状態", "Estado actual", "Stato attuale", "Núverandi staða", "Status praesens"),
    "版本": _row("版本", "Version", "バージョン", "Versión", "Versione", "Útgáfa", "Versio"),
    "自动化引擎": _row("自动化引擎", "Automation engine", "自動化エンジン", "Motor de automatización", "Motore di automazione", "Sjálfvirknivél", "Machina automationis"),
    "未运行": _row("未运行", "Not running", "停止中", "No está en ejecución", "Non in esecuzione", "Ekki í gangi", "Non currit"),
    "当前流程": _row("当前流程", "Current workflow", "現在のフロー", "Flujo actual", "Flusso attuale", "Núverandi flæði", "Fluxus praesens"),
    "无": _row("无", "None", "なし", "Ninguno", "Nessuno", "Ekkert", "Nullum"),
    "项目数据": _row("项目数据", "Project data", "プロジェクトデータ", "Datos del proyecto", "Dati progetto", "Verkefnisgögn", "Data projecti"),
    "运行日志和命令输出会显示在这里。": _row("运行日志和命令输出会显示在这里。", "Runtime logs and command output appear here.", "実行ログとコマンド出力を表示します。", "Aquí se muestran los registros y la salida de comandos.", "Qui vengono mostrati log e output dei comandi.", "Hér birtast keyrsluskrár og skipanaúttak.", "Hic acta executionis et exitus mandatorum ostenduntur."),
    "输入 UVAF 指令；使用 !command 执行系统命令": _row("输入 UVAF 指令；使用 !command 执行系统命令", "Enter a UVAF command; use !command for system commands", "UVAF コマンドを入力；!command でシステムコマンドを実行", "Introduce un comando UVAF; usa !command para comandos del sistema", "Inserisci un comando UVAF; usa !command per i comandi di sistema", "Sláðu inn UVAF-skipun; notaðu !command fyrir kerfisskipanir", "Mandatum UVAF insere; !command ad mandata systematis utere"),
    "执行": _row("执行", "Execute", "実行", "Ejecutar", "Esegui", "Framkvæma", "Exsequere"),
    "框选区域颜色报告": _row("框选区域颜色报告", "Selected-area color report", "選択領域の色レポート", "Informe de color del área seleccionada", "Rapporto colori area selezionata", "Litaskýrsla valsvæðis", "Relatio colorum areae selectae"),
    "框选": _row("框选", "Select area", "範囲選択", "Seleccionar área", "Seleziona area", "Velja svæði", "Areā selige"),
    "颜色": _row("颜色", "Color", "色", "Color", "Colore", "Litur", "Color"),
    "像素数": _row("像素数", "Pixels", "ピクセル数", "Píxeles", "Pixel", "Dílar", "Pixela"),
    "占比": _row("占比", "Share", "割合", "Proporción", "Quota", "Hlutfall", "Proportio"),
    "当前项目中的可复用模块组合。": _row("当前项目中的可复用模块组合。", "Reusable module groups in the current project.", "現在のプロジェクトで再利用できるモジュールグループ。", "Grupos de módulos reutilizables del proyecto actual.", "Gruppi di moduli riutilizzabili nel progetto corrente.", "Endurnýtanlegir einingahópar í núverandi verkefni.", "Coetus modulorum reutilizabiles in projecto praesenti."),
    "创建或导入项目后开始。": _row("创建或导入项目后开始。", "Create or import a project to begin.", "プロジェクトを作成またはインポートして開始します。", "Crea o importa un proyecto para empezar.", "Crea o importa un progetto per iniziare.", "Búðu til eða flyttu inn verkefni til að byrja.", "Projectum crea vel importa ut incipias."),
    "简单模式（拼图）": _row("简单模式（拼图）", "Simple mode (Puzzle)", "シンプルモード（パズル）", "Modo simple (puzle)", "Modalità semplice (puzzle)", "Einfaldur hamur (púsl)", "Modus simplex (tesserae)"),
    "复杂模式：节点、端口与连线。": _row("复杂模式：节点、端口与连线。", "Complex mode: nodes, ports and wires.", "複雑モード：ノード、ポート、接続。", "Modo complejo: nodos, puertos y enlaces.", "Modalità complessa: nodi, porte e collegamenti.", "Flókinn hamur: hnútar, tengi og línur.", "Modus complexus: nodi, portae et nexus."),
})

_TRANSLATIONS.update({
    "匹配度": _row("匹配度", "Match", "一致度", "Coincidencia", "Corrispondenza", "Samsvörun", "Concordantia"),
    "选择模板": _row("选择模板", "Choose template", "テンプレートを選択", "Elegir plantilla", "Scegli modello", "Velja sniðmát", "Exemplar elige"),
    "选择锚点": _row("选择锚点", "Choose anchor", "アンカーを選択", "Elegir ancla", "Scegli ancora", "Velja akkeri", "Ancoram elige"),
    "ROI框选": _row("ROI框选", "Select ROI", "ROI範囲選択", "Seleccionar ROI", "Seleziona ROI", "Velja ROI", "ROI selige"),
    "锚点框选": _row("锚点框选", "Capture anchor", "アンカー範囲選択", "Capturar ancla", "Cattura ancora", "Taka akkeri", "Ancoram cape"),
    "空": _row("空", "None", "なし", "Ninguno", "Nessuno", "Ekkert", "Nullum"),
    "锚点": _row("锚点", "Anchor", "アンカー", "Ancla", "Ancora", "Akkeri", "Ancora"),
    "循环任务（重复）": _row("循环任务（重复）", "Loop task (repeat)", "ループ処理（反復）", "Tarea de bucle (repetir)", "Attività ciclo (ripeti)", "Lykkjuverk (endurtekið)", "Munus iterationis (repete)"),
    "直到": _row("直到", "Until", "まで", "Hasta", "Finché", "Þar til", "Donec"),
    "IF · 判定": _row("IF · 判定", "IF · Condition", "IF・条件", "IF · Condición", "IF · Condizione", "IF · Skilyrði", "IF · Condicio"),
    "THEN · 执行": _row("THEN · 执行", "THEN · Execute", "THEN・実行", "THEN · Ejecutar", "THEN · Esegui", "THEN · Keyra", "THEN · Exsequere"),
    "条件 A": _row("条件 A", "Condition A", "条件 A", "Condición A", "Condizione A", "Skilyrði A", "Condicio A"),
    "条件 B": _row("条件 B", "Condition B", "条件 B", "Condición B", "Condizione B", "Skilyrði B", "Condicio B"),
    "任一满足后执行": _row("任一满足后执行", "Execute if either is true", "いずれか成立で実行", "Ejecutar si cualquiera se cumple", "Esegui se uno è vero", "Keyra ef annað er satt", "Exsequere si alterutrum verum est"),
    "均不满足后执行": _row("均不满足后执行", "Execute if neither is true", "どちらも不成立なら実行", "Ejecutar si ninguno se cumple", "Esegui se nessuno è vero", "Keyra ef hvorugt er satt", "Exsequere si neutrum verum est"),
    "两者均满足后执行": _row("两者均满足后执行", "Execute if both are true", "両方成立で実行", "Ejecutar si ambos se cumplen", "Esegui se entrambi sono veri", "Keyra ef bæði eru sönn", "Exsequere si ambo vera sunt"),
    "无限循环": _row("无限循环", "Infinite loop", "無限ループ", "Bucle infinito", "Ciclo infinito", "Óendanleg lykkja", "Iteratio infinita"),
    "循环次数": _row("循环次数", "Loop count", "ループ回数", "Número de bucles", "Numero cicli", "Fjöldi lykkja", "Numerus iterationum"),
    "取消": _row("取消", "Cancel", "キャンセル", "Cancelar", "Annulla", "Hætta við", "Cancella"),
    "确定": _row("确定", "OK", "決定", "Aceptar", "OK", "Í lagi", "Confirma"),
    "新建自定义模块": _row("新建自定义模块", "New custom module", "新規カスタムモジュール", "Nuevo módulo personalizado", "Nuovo modulo personalizzato", "Ný sérsniðin eining", "Novus modulus consuetudinalis"),
    "自定义模块名称：": _row("自定义模块名称：", "Custom module name:", "カスタムモジュール名：", "Nombre del módulo personalizado:", "Nome modulo personalizzato:", "Heiti sérsniðinnar einingar:", "Nomen moduli consuetudinalis:"),
})

# ---------------------------------------------------------------------------
# Extended UI coverage
# ---------------------------------------------------------------------------
# These entries intentionally include both full explanatory sentences and
# reusable fragments. Full sentences keep the UI natural; fragments allow
# dynamic labels containing coordinates, counts, filenames, etc. to translate
# without requiring one translation entry for every runtime value.
_TRANSLATIONS.update({
    # Settings / hotkey recorder
    "未绑定": _row("未绑定", "Unbound", "未割り当て", "Sin asignar", "Non assegnato", "Óbundið", "Non ligatum"),
    "请按下要绑定的按键组合": _row("请按下要绑定的按键组合", "Press the key combination to bind", "割り当てるキーの組み合わせを押してください", "Pulsa la combinación de teclas que quieras asignar", "Premi la combinazione di tasti da assegnare", "Ýttu á lyklasamsetninguna sem á að binda", "Preme coniunctionem clavium ligandam"),
    "从第一个键按下开始录制。只要其中还有按键没有松开，就会继续记录后续按下的键；当本次组合中的所有按键都松开后自动完成。": _row(
        "从第一个键按下开始录制。只要其中还有按键没有松开，就会继续记录后续按下的键；当本次组合中的所有按键都松开后自动完成。",
        "Recording starts with the first key press. Additional keys are included while any recorded key remains held; recording finishes when every key in the chord is released.",
        "最初のキーを押した時点で記録を開始します。記録中のキーが1つでも押されたままなら後続のキーも追加され、組み合わせ内のすべてのキーを離すと記録が完了します。",
        "La grabación empieza al pulsar la primera tecla. Mientras alguna tecla siga pulsada se añadirán las siguientes; termina cuando se suelten todas las teclas de la combinación.",
        "La registrazione inizia alla prima pressione. Finché almeno un tasto resta premuto vengono aggiunti i tasti successivi; termina quando tutti i tasti della combinazione vengono rilasciati.",
        "Upptaka hefst þegar fyrsti lykillinn er ýttur. Á meðan einhver skráður lykill er niðri bætast fleiri lyklar við; upptökunni lýkur þegar öllum lyklum samsetningarinnar er sleppt.",
        "Registratio incipit prima clave pressa. Dum aliqua clavis retinetur, claves sequentes adduntur; finitur cum omnes claves coniunctionis dimittuntur."
    ),
    "简单模式使用拼图磁吸；复杂模式采用类似 World Machine 的节点、端口和连线。": _row(
        "简单模式使用拼图磁吸；复杂模式采用类似 World Machine 的节点、端口和连线。",
        "Simple mode uses puzzle-style snapping; Complex mode uses World Machine-like nodes, ports and wires.",
        "シンプルモードはパズル式のスナップ接続、複雑モードは World Machine のようなノード・ポート・配線を使用します。",
        "El modo simple usa encaje tipo puzle; el modo complejo usa nodos, puertos y conexiones al estilo de World Machine.",
        "La modalità semplice usa l'aggancio a puzzle; quella complessa usa nodi, porte e collegamenti simili a World Machine.",
        "Einfaldur hamur notar púsl-tengingu; flókinn hamur notar hnúta, tengi og línur líkt og World Machine.",
        "Modus simplex tessellis magnetice coniungitur; modus complexus nodis, portis et nexibus more World Machine utitur."
    ),
    "默认：快捷建立模板 Ctrl+S；视觉识别系统视角 Ctrl+L。录制支持 Ctrl+Shift+K 等组合；第一个键按下后会持续记录，直到本次组合的所有按键最终全部松开。": _row(
        "默认：快捷建立模板 Ctrl+S；视觉识别系统视角 Ctrl+L。录制支持 Ctrl+Shift+K 等组合；第一个键按下后会持续记录，直到本次组合的所有按键最终全部松开。",
        "Defaults: Quick template capture Ctrl+S; Recognition viewport Ctrl+L. Recording supports chords such as Ctrl+Shift+K and continues until every key in the chord has been released.",
        "既定値：クイックテンプレート作成 Ctrl+S、認識ビュー Ctrl+L。Ctrl+Shift+K のような組み合わせに対応し、組み合わせ内の全キーを離すまで記録します。",
        "Predeterminados: captura rápida Ctrl+S; vista de reconocimiento Ctrl+L. La grabación admite combinaciones como Ctrl+Shift+K y continúa hasta soltar todas las teclas.",
        "Predefiniti: acquisizione rapida Ctrl+S; vista riconoscimento Ctrl+L. La registrazione supporta combinazioni come Ctrl+Shift+K e continua finché tutti i tasti vengono rilasciati.",
        "Sjálfgefið: flýtisniðmát Ctrl+S; greiningarsýn Ctrl+L. Upptaka styður samsetningar eins og Ctrl+Shift+K og heldur áfram þar til öllum lyklum er sleppt.",
        "Praedefinita: exemplar celeriter Ctrl+S; prospectus recognitionis Ctrl+L. Coniunctiones ut Ctrl+Shift+K sustinentur et registratio durat donec omnes claves dimittantur."
    ),
    "UVAF Native（推荐：DXCam 优先，MSS 回退）": _row("UVAF Native（推荐：DXCam 优先，MSS 回退）", "UVAF Native (recommended: DXCam first, MSS fallback)", "UVAF Native（推奨：DXCam 優先、MSS フォールバック）", "UVAF Native (recomendado: DXCam primero, MSS como respaldo)", "UVAF Native (consigliato: DXCam prioritario, MSS fallback)", "UVAF Native (mælt með: DXCam fyrst, MSS vara)", "UVAF Native (commendatum: DXCam primum, MSS subsidiarium)"),
    "MSS 兼容后端": _row("MSS 兼容后端", "MSS compatibility backend", "MSS 互換バックエンド", "Backend compatible MSS", "Backend compatibile MSS", "MSS-samhæft bakendi", "Pars posterior MSS compatibilis"),
    "PyAutoGUI 兼容后端": _row("PyAutoGUI 兼容后端", "PyAutoGUI compatibility backend", "PyAutoGUI 互換バックエンド", "Backend compatible PyAutoGUI", "Backend compatibile PyAutoGUI", "PyAutoGUI-samhæft bakendi", "Pars posterior PyAutoGUI compatibilis"),
    "开启后会尽量让 Windows 截图和 Recognition Engine 忽略视觉识别视角窗口，避免递归套娃；关闭时可正常截取该调试窗口。": _row(
        "开启后会尽量让 Windows 截图和 Recognition Engine 忽略视觉识别视角窗口，避免递归套娃；关闭时可正常截取该调试窗口。",
        "When enabled, Windows capture and the Recognition Engine try to exclude the recognition viewport to avoid recursive capture. Disable it if you need to capture the debug window itself.",
        "有効にすると、再帰的な映り込みを避けるため Windows キャプチャと Recognition Engine が認識ビューを除外します。デバッグウィンドウ自体を撮影する場合は無効にしてください。",
        "Al activarlo, la captura de Windows y Recognition Engine intentan excluir la vista de reconocimiento para evitar capturas recursivas. Desactívalo para capturar la propia ventana de depuración.",
        "Se attivo, la cattura Windows e Recognition Engine cercano di escludere la vista di riconoscimento per evitare catture ricorsive. Disattivalo per catturare la finestra di debug.",
        "Þegar þetta er virkt reyna Windows-upptaka og Recognition Engine að útiloka greiningargluggann til að forðast endurkvæma mynd. Slökktu á þessu til að taka sjálfan kembigluggan.",
        "Cum activum est, captio Windows et Recognition Engine prospectum recognitionis excludere conantur ne imago recursive capiatur. Exstingue ut ipsam fenestram diagnosticam capias."
    ),
    "这里选择的是截图/识别执行后端，而不是模板算法。扫描模板自己的彩色、灰度、RGB、HSV、边缘、FeatureMatch 等算法在模块设置中独立选择；默认全部启用。最大识别帧率是抓取新画面的上限，实际速度仍取决于识别耗时。": _row(
        "这里选择的是截图/识别执行后端，而不是模板算法。扫描模板自己的彩色、灰度、RGB、HSV、边缘、FeatureMatch 等算法在模块设置中独立选择；默认全部启用。最大识别帧率是抓取新画面的上限，实际速度仍取决于识别耗时。",
        "This selects the capture/recognition execution backend, not a template algorithm. Color, grayscale, RGB, HSV, edge and FeatureMatch methods are chosen independently in each visual module and are enabled by default. Maximum recognition FPS limits new-frame capture; actual speed still depends on recognition cost.",
        "ここで選択するのは撮影・認識の実行バックエンドであり、テンプレートアルゴリズムではありません。カラー、グレースケール、RGB、HSV、エッジ、FeatureMatch は各視覚モジュールで個別に選択でき、既定ではすべて有効です。最大認識 FPS は新規フレーム取得の上限で、実速度は認識処理時間にも依存します。",
        "Aquí se selecciona el backend de captura/reconocimiento, no el algoritmo de plantilla. Color, escala de grises, RGB, HSV, bordes y FeatureMatch se eligen por separado en cada módulo visual y están activados por defecto. El FPS máximo limita la captura de nuevos fotogramas; la velocidad real también depende del coste del reconocimiento.",
        "Qui si seleziona il backend di cattura/riconoscimento, non l'algoritmo del modello. Colore, scala di grigi, RGB, HSV, bordi e FeatureMatch si scelgono separatamente in ogni modulo visivo e sono attivi per impostazione predefinita. L'FPS massimo limita l'acquisizione di nuovi fotogrammi; la velocità effettiva dipende anche dal costo del riconoscimento.",
        "Hér er valið bakendi fyrir skjámynd/greiningu, ekki sniðmátsreiknirit. Litur, grátónn, RGB, HSV, jaðar og FeatureMatch eru valin sjálfstætt í hverri sjónrænni einingu og eru sjálfgefið virk. Hámarks-FPS takmarkar nýja ramma; raunhraði ræðst einnig af greiningartíma.",
        "Hic eligitur pars posterior captionis/recognitionis, non algorithmus exemplaris. Color, scala cinerea, RGB, HSV, margines et FeatureMatch in singulis modulis visualibus separatim eliguntur et praedefinite activa sunt. Maxima frequentia recognitionis novos quadros limitat; velocitas vera etiam sumptu recognitionis pendet."
    ),
    "录制：快捷建立模板": _row("录制：快捷建立模板", "Record: Quick template capture", "記録：クイックテンプレート作成", "Grabar: Captura rápida de plantilla", "Registra: acquisizione rapida modello", "Taka upp: flýtisniðmát", "Registra: exemplar celeriter"),
    "录制：视觉识别系统视角": _row("录制：视觉识别系统视角", "Record: Recognition viewport", "記録：認識ビュー", "Grabar: Vista de reconocimiento", "Registra: vista riconoscimento", "Taka upp: greiningarsýn", "Registra: prospectus recognitionis"),
    "确定恢复 UVAF 的默认设置吗？": _row("确定恢复 UVAF 的默认设置吗？", "Restore UVAF's default settings?", "UVAF の既定設定に戻しますか？", "¿Restaurar la configuración predeterminada de UVAF?", "Ripristinare le impostazioni predefinite di UVAF?", "Endurheimta sjálfgefnar stillingar UVAF?", "Configurationes praedefinitas UVAF restitues?"),
    "热键冲突": _row("热键冲突", "Hotkey conflict", "ホットキーの競合", "Conflicto de atajos", "Conflitto tasti rapidi", "Árekstur flýtilykla", "Conflictus clavium"),
    "已经绑定给另一个功能，请录制不同的组合。": _row("已经绑定给另一个功能，请录制不同的组合。", "is already assigned to another function. Record a different chord.", "は別の機能に割り当て済みです。別の組み合わせを記録してください。", "ya está asignado a otra función. Graba una combinación diferente.", "è già assegnato a un'altra funzione. Registra una combinazione diversa.", "er þegar bundið annarri aðgerð. Taktu upp aðra samsetningu.", "iam alteri muneri ligatum est. Aliam coniunctionem registra."),
    "无法打开文件夹": _row("无法打开文件夹", "Unable to open folder", "フォルダーを開けません", "No se puede abrir la carpeta", "Impossibile aprire la cartella", "Ekki tókst að opna möppu", "Directorium aperiri non potest"),

    # Utilities
    "一些独立于自动化流程的辅助分析工具。": _row("一些独立于自动化流程的辅助分析工具。", "Auxiliary analysis tools that operate independently of automation workflows.", "自動化ワークフローとは独立して使える補助分析ツールです。", "Herramientas auxiliares de análisis independientes de los flujos de automatización.", "Strumenti di analisi ausiliari indipendenti dai flussi di automazione.", "Hjálpargreiningartæki sem starfa óháð sjálfvirkniflæði.", "Instrumenta analytica auxiliaria a fluxibus automationis independentia."),
    "默认使用 Windows 物理全局坐标。": _row("默认使用 Windows 物理全局坐标。", "Uses Windows physical global coordinates by default.", "既定では Windows の物理グローバル座標を使用します。", "Usa por defecto las coordenadas físicas globales de Windows.", "Usa per impostazione predefinita le coordinate fisiche globali di Windows.", "Notar sjálfgefið hnattræn Windows-raunhnit.", "Praedefinite coordinatis physicis globalibus Windows utitur."),
    "未启动 · 启动后每 0.2 秒刷新一次鼠标全局坐标。": _row("未启动 · 启动后每 0.2 秒刷新一次鼠标全局坐标。", "Stopped · When started, global mouse coordinates refresh every 0.2 s.", "停止中 · 開始するとマウスのグローバル座標を 0.2 秒ごとに更新します。", "Detenido · Al iniciar, las coordenadas globales del ratón se actualizan cada 0,2 s.", "Fermo · Dopo l'avvio, le coordinate globali del mouse si aggiornano ogni 0,2 s.", "Stöðvað · Eftir ræsingu uppfærast hnattræn músarhnit á 0,2 sek. fresti.", "Sistit · Post initium coordinatae globales muris singulis 0.2 s renovantur."),
    "监视器启动后按 K 记录当前坐标。默认记录全屏坐标；选择当前项目模板作为锚点后，记录相对于该锚点左上角的坐标。": _row(
        "监视器启动后按 K 记录当前坐标。默认记录全屏坐标；选择当前项目模板作为锚点后，记录相对于该锚点左上角的坐标。",
        "After starting the monitor, press K to record the current coordinate. Fullscreen coordinates are used by default; choose a project template as an anchor to record coordinates relative to its top-left corner.",
        "モニター開始後に K を押すと現在座標を記録します。既定では全画面座標を使用し、プロジェクトのテンプレートをアンカーに選ぶとその左上を原点とした相対座標を記録します。",
        "Tras iniciar el monitor, pulsa K para registrar la coordenada actual. Por defecto usa coordenadas de pantalla completa; selecciona una plantilla del proyecto como ancla para registrar coordenadas relativas a su esquina superior izquierda.",
        "Dopo aver avviato il monitor premi K per registrare la coordinata corrente. Per impostazione predefinita usa coordinate a schermo intero; scegli un modello del progetto come ancora per registrare coordinate relative al suo angolo superiore sinistro.",
        "Eftir að vaktin er ræst skráir K núverandi hnit. Sjálfgefið eru heildarskjáhnit notuð; veldu sniðmát verkefnis sem akkeri til að skrá hnit miðað við efra vinstra horn þess.",
        "Post monitoris initium preme K ut coordinatam praesentem registres. Praedefinite coordinatae totius scrinii adhibentur; exemplar projecti ut ancoram elige ut coordinatae ab angulo superiore sinistro relativa scribantur."
    ),
    "点击“框选”，然后拖动选择屏幕区域。报告会列出该区域出现的每一种精确 RGB 颜色。": _row("点击“框选”，然后拖动选择屏幕区域。报告会列出该区域出现的每一种精确 RGB 颜色。", "Click “Select area”, then drag to choose a screen region. The report lists every exact RGB color present in that region.", "「範囲選択」をクリックして画面領域をドラッグ選択します。レポートにはその領域に存在する正確な RGB 色がすべて表示されます。", "Haz clic en «Seleccionar área» y arrastra para elegir una región. El informe mostrará cada color RGB exacto presente.", "Fai clic su «Seleziona area» e trascina per scegliere una regione. Il rapporto elenca ogni colore RGB esatto presente.", "Smelltu á „Velja svæði“ og dragðu til að velja skjásvæði. Skýrslan sýnir hvern nákvæman RGB-lit á svæðinu.", "Preme «Areā selige» deinde trahe ut regionem scrinii eligas. Relatio omnes colores RGB exactos in regione enumerat."),
    "Recognition Engine 不可用。": _row("Recognition Engine 不可用。", "Recognition Engine is unavailable.", "Recognition Engine を利用できません。", "Recognition Engine no está disponible.", "Recognition Engine non è disponibile.", "Recognition Engine er ekki tiltækt.", "Recognition Engine praesto non est."),
    "锚点模板文件不存在。": _row("锚点模板文件不存在。", "The anchor template file does not exist.", "アンカーテンプレートファイルが存在しません。", "El archivo de plantilla del ancla no existe.", "Il file del modello ancora non esiste.", "Akkerissniðmátsskráin er ekki til.", "Fasciculus exemplaris ancorae non exstat."),
    "序号": _row("序号", "No.", "番号", "N.º", "N.", "Nr.", "N."),
    "记录时间": _row("记录时间", "Recorded at", "記録時刻", "Hora de registro", "Ora registrazione", "Skráð", "Tempus"),
    "坐标系：全屏全局坐标。": _row("坐标系：全屏全局坐标。", "Coordinate system: fullscreen global coordinates.", "座標系：全画面グローバル座標。", "Sistema de coordenadas: coordenadas globales de pantalla completa.", "Sistema di coordinate: coordinate globali dello schermo.", "Hnitakerfi: hnattræn heildarskjáhnit.", "Systema coordinatarum: coordinatae globales totius scrinii."),
    "已停止 · 再次点击“启动”可继续监视。": _row("已停止 · 再次点击“启动”可继续监视。", "Stopped · Click “Start” again to resume monitoring.", "停止中 · もう一度「開始」をクリックすると監視を再開します。", "Detenido · Haz clic de nuevo en «Iniciar» para reanudar.", "Fermo · Fai di nuovo clic su «Avvia» per riprendere.", "Stöðvað · Smelltu aftur á „Ræsa“ til að halda áfram.", "Sistit · «Inicia» iterum preme ut monitorem resumes."),
    "未找到锚点": _row("未找到锚点", "Anchor not found", "アンカーが見つかりません", "Ancla no encontrada", "Ancora non trovata", "Akkeri fannst ekki", "Ancora non inventa"),
    "Windows user32 后端不可用。": _row("Windows user32 后端不可用。", "Windows user32 backend is unavailable.", "Windows user32 バックエンドを利用できません。", "El backend user32 de Windows no está disponible.", "Il backend user32 di Windows non è disponibile.", "Windows user32 bakendi er ekki tiltækt.", "Pars posterior Windows user32 praesto non est."),
    "Windows GetCursorPos 失败。": _row("Windows GetCursorPos 失败。", "Windows GetCursorPos failed.", "Windows GetCursorPos に失敗しました。", "Windows GetCursorPos falló.", "Windows GetCursorPos non riuscito.", "Windows GetCursorPos mistókst.", "Windows GetCursorPos defecit."),
    "全屏(Windows)": _row("全屏(Windows)", "Fullscreen (Windows)", "全画面 (Windows)", "Pantalla completa (Windows)", "Schermo intero (Windows)", "Allur skjár (Windows)", "Totum scrinium (Windows)"),
    "正在定位锚点…": _row("正在定位锚点…", "Locating anchor…", "アンカーを検出中…", "Localizando ancla…", "Ricerca ancora…", "Leita að akkeri…", "Ancora quaeritur…"),
    "当前锚点尚未识别，本次 K 不记录坐标。": _row("当前锚点尚未识别，本次 K 不记录坐标。", "The current anchor has not been recognized; this K press will not record a coordinate.", "現在のアンカーがまだ認識されていないため、この K 入力では座標を記録しません。", "El ancla actual aún no se ha reconocido; esta pulsación de K no registrará coordenadas.", "L'ancora corrente non è ancora riconosciuta; questa pressione di K non registrerà coordinate.", "Núverandi akkeri hefur ekki fundist; þessi K-ýting skráir ekki hnit.", "Ancora praesens nondum agnita est; haec pressio K coordinatam non registrabit."),
    "记录已清空。": _row("记录已清空。", "Records cleared.", "記録を消去しました。", "Registros borrados.", "Registrazioni cancellate.", "Skrár hreinsaðar.", "Registrationes purgatae."),
    "当前没有打开项目；仅可使用全屏坐标。": _row("当前没有打开项目；仅可使用全屏坐标。", "No project is open; only fullscreen coordinates are available.", "プロジェクトが開かれていないため、全画面座標のみ使用できます。", "No hay un proyecto abierto; solo están disponibles las coordenadas de pantalla completa.", "Nessun progetto aperto; sono disponibili solo le coordinate a schermo intero.", "Ekkert verkefni er opið; aðeins heildarskjáhnit eru tiltæk.", "Nullum projectum apertum est; solae coordinatae totius scrinii praesto sunt."),
    "当前项目模板库为空；默认使用全屏坐标。": _row("当前项目模板库为空；默认使用全屏坐标。", "The current project template library is empty; fullscreen coordinates are used by default.", "現在のプロジェクトのテンプレートライブラリは空です。既定では全画面座標を使用します。", "La biblioteca de plantillas del proyecto actual está vacía; se usan coordenadas de pantalla completa por defecto.", "La libreria modelli del progetto corrente è vuota; per impostazione predefinita vengono usate coordinate a schermo intero.", "Sniðmátasafn verkefnisins er tómt; heildarskjáhnit eru notuð sjálfgefið.", "Bibliotheca exemplarium projecti vacua est; coordinatae totius scrinii praedefinite adhibentur."),

    # Workbench / module descriptions
    "检测画面、窗口或状态，并输出结果。": _row("检测画面、窗口或状态，并输出结果。", "Detect screen, window or state information and output results.", "画面・ウィンドウ・状態を検出して結果を出力します。", "Detecta información de pantalla, ventana o estado y genera resultados.", "Rileva schermo, finestra o stato e produce risultati.", "Greinir skjá, glugga eða stöðu og skilar niðurstöðum.", "Scrinium, fenestram vel statum detegit et resultata edit."),
    "根据状态执行点击、键盘等操作。": _row("根据状态执行点击、键盘等操作。", "Perform clicks, keyboard input and other actions based on state.", "状態に応じてクリックやキーボード入力などを実行します。", "Ejecuta clics, teclado y otras acciones según el estado.", "Esegue clic, input da tastiera e altre azioni in base allo stato.", "Framkvæmir smelli, lyklaborð og aðrar aðgerðir eftir stöðu.", "Clic, ingressum claviaturae aliasque actiones ex statu exsequitur."),
    "负责 ROI、条件、分支、循环和流程顺序。": _row("负责 ROI、条件、分支、循环和流程顺序。", "Controls ROI, conditions, branches, loops and workflow order.", "ROI、条件、分岐、ループ、フロー順序を制御します。", "Controla ROI, condiciones, ramas, bucles y el orden del flujo.", "Gestisce ROI, condizioni, rami, cicli e ordine del flusso.", "Stýrir ROI, skilyrðum, greinum, lykkjum og röð flæðis.", "ROI, condiciones, ramos, iterationes ordinemque fluxus regit."),
    "保存、转换和比较流程中的数据。": _row("保存、转换和比较流程中的数据。", "Store, transform and compare workflow data.", "ワークフロー内のデータを保存・変換・比較します。", "Guarda, transforma y compara datos del flujo.", "Salva, trasforma e confronta i dati del flusso.", "Geymir, umbreytir og ber saman gögn flæðis.", "Data fluxus servat, transformat et comparat."),
    "检查流程中的数据与运行状态。": _row("检查流程中的数据与运行状态。", "Inspect workflow data and runtime state.", "ワークフローのデータと実行状態を確認します。", "Inspecciona los datos del flujo y el estado de ejecución.", "Ispeziona dati del flusso e stato di esecuzione.", "Skoðar flæðisgögn og keyrslustöðu.", "Data fluxus statumque executionis inspicit."),
    "连接到起始执行链后，对后续流程全局生效。": _row("连接到起始执行链后，对后续流程全局生效。", "When connected to a start chain, applies globally to subsequent workflow execution.", "開始チェーンに接続すると、その後のワークフロー全体に適用されます。", "Al conectarse a una cadena de inicio, se aplica globalmente al flujo posterior.", "Collegato a una catena di avvio, si applica globalmente al flusso successivo.", "Þegar tengt er við upphafskeðju gildir það víðvært fyrir áframhaldandi flæði.", "Catenae initiali conexum, globaliter ad fluxum sequentem valet."),
    "定义流程开始和触发方式。": _row("定义流程开始和触发方式。", "Define how workflows start and are triggered.", "ワークフローの開始方法とトリガーを定義します。", "Define cómo se inicia y activa el flujo.", "Definisce avvio e attivazione del flusso.", "Skilgreinir hvernig flæði hefst og virkjast.", "Definit quomodo fluxus incipiat et excitatur."),
    "快速查看项目结构。": _row("快速查看项目结构。", "Quickly inspect the project structure.", "プロジェクト構造をすばやく確認します。", "Consulta rápidamente la estructura del proyecto.", "Visualizza rapidamente la struttura del progetto.", "Skoðaðu verkefnaskipan fljótt.", "Structuram projecti celeriter inspice."),
    "就绪": _row("就绪", "Ready", "準備完了", "Listo", "Pronto", "Tilbúið", "Paratum"),
    "每个项目拥有独立的模板、资源和工作流。": _row("每个项目拥有独立的模板、资源和工作流。", "Each project has its own templates, resources and workflows.", "各プロジェクトは独立したテンプレート、リソース、ワークフローを持ちます。", "Cada proyecto tiene sus propias plantillas, recursos y flujos.", "Ogni progetto ha modelli, risorse e flussi indipendenti.", "Hvert verkefni hefur eigin sniðmát, tilföng og flæði.", "Quodque projectum exemplaria, opes et fluxus proprios habet."),

    # Common module/dialog vocabulary
    "文本": _row("文本", "Text", "テキスト", "Texto", "Testo", "Texti", "Textus"),
    "次数": _row("次数", "Count", "回数", "Veces", "Numero", "Fjöldi", "Numerus"),
    "模式": _row("模式", "Mode", "モード", "Modo", "Modalità", "Hamur", "Modus"),
    "普通模式": _row("普通模式", "Normal mode", "通常モード", "Modo normal", "Modalità normale", "Venjulegur hamur", "Modus ordinarius"),
    "高级模式": _row("高级模式", "Advanced mode", "詳細モード", "Modo avanzado", "Modalità avanzata", "Ítarlegur hamur", "Modus provectus"),
    "高级设置": _row("高级设置", "Advanced settings", "詳細設定", "Ajustes avanzados", "Impostazioni avanzate", "Ítarlegar stillingar", "Configurationes provectae"),
    "上": _row("上", "Up", "上", "Arriba", "Su", "Upp", "Sursum"),
    "下": _row("下", "Down", "下", "Abajo", "Giù", "Niður", "Deorsum"),
    "左": _row("左", "Left", "左", "Izquierda", "Sinistra", "Vinstri", "Sinistra"),
    "右": _row("右", "Right", "右", "Derecha", "Destra", "Hægri", "Dextera"),
    "毫秒": _row("毫秒", "ms", "ミリ秒", "ms", "ms", "ms", "ms"),
    "秒": _row("秒", "seconds", "秒", "segundos", "secondi", "sekúndur", "secunda"),
    "分钟": _row("分钟", "minutes", "分", "minutos", "minuti", "mínútur", "minuta"),
    "小时": _row("小时", "hours", "時間", "horas", "ore", "klukkustundir", "horae"),
    "时长": _row("时长", "Duration", "時間", "Duración", "Durata", "Tímalengd", "Duratio"),
    "数值": _row("数值", "Value", "値", "Valor", "Valore", "Gildi", "Valor"),
    "程序路径": _row("程序路径", "Program path", "プログラムパス", "Ruta del programa", "Percorso programma", "Forritsslóð", "Via programmatis"),
    "浏览…": _row("浏览…", "Browse…", "参照…", "Examinar…", "Sfoglia…", "Fletta…", "Quaere…"),
    "应用": _row("应用", "Apply", "適用", "Aplicar", "Applica", "Virkja", "Applica"),
    "清除锚点": _row("清除锚点", "Clear anchor", "アンカーを解除", "Borrar ancla", "Rimuovi ancora", "Hreinsa akkeri", "Ancoram purga"),
    "空（全屏坐标）": _row("空（全屏坐标）", "None (fullscreen coordinates)", "なし（全画面座標）", "Ninguno (coordenadas de pantalla completa)", "Nessuno (coordinate schermo intero)", "Ekkert (heildarskjáhnit)", "Nullum (coordinatae totius scrinii)"),
    "固定坐标设置": _row("固定坐标设置", "Fixed coordinate settings", "固定座標設定", "Ajustes de coordenada fija", "Impostazioni coordinata fissa", "Stillingar fastra hnita", "Configurationes coordinatae fixae"),
    "坐标修改设置": _row("坐标修改设置", "Coordinate modification settings", "座標変更設定", "Ajustes de modificación de coordenadas", "Impostazioni modifica coordinate", "Stillingar hnitabreytinga", "Configurationes mutationis coordinatarum"),
    "移至设置": _row("移至设置", "Move-to settings", "移動設定", "Ajustes de movimiento", "Impostazioni spostamento", "Færslustillingar", "Configurationes motus"),
    "点击设置": _row("点击设置", "Click settings", "クリック設定", "Ajustes de clic", "Impostazioni clic", "Smellistillingar", "Configurationes pressionis"),
    "拖动设置": _row("拖动设置", "Drag settings", "ドラッグ設定", "Ajustes de arrastre", "Impostazioni trascinamento", "Dragstillingar", "Configurationes tractus"),
    "键盘输入设置": _row("键盘输入设置", "Keyboard input settings", "キーボード入力設定", "Ajustes de entrada de teclado", "Impostazioni input tastiera", "Lyklaborðsstillingar", "Configurationes claviaturae"),
    "启动程序设置": _row("启动程序设置", "Launch program settings", "プログラム起動設定", "Ajustes de inicio de programa", "Impostazioni avvio programma", "Stillingar forritsræsingar", "Configurationes initiationis programmatis"),
    "延时等待设置": _row("延时等待设置", "Delay settings", "待機設定", "Ajustes de espera", "Impostazioni attesa", "Biðstillingar", "Configurationes morae"),
    "时钟设置": _row("时钟设置", "Clock settings", "タイマー設定", "Ajustes de reloj", "Impostazioni timer", "Klukkustillingar", "Configurationes horologii"),
    "扫描模板设置": _row("扫描模板设置", "Scan template settings", "テンプレート走査設定", "Ajustes de escaneo de plantilla", "Impostazioni scansione modello", "Stillingar sniðmátaskönnunar", "Configurationes explorationis exemplaris"),
    "模板计数设置": _row("模板计数设置", "Template count settings", "テンプレート数設定", "Ajustes de conteo de plantilla", "Impostazioni conteggio modello", "Stillingar sniðmátatalningar", "Configurationes numerationis exemplarium"),
    "锁定模板设置": _row("锁定模板设置", "Lock template settings", "テンプレート追跡設定", "Ajustes de bloqueo de plantilla", "Impostazioni blocco modello", "Stillingar sniðmátslásar", "Configurationes fixationis exemplaris"),
    "视觉识别设置": _row("视觉识别设置", "Visual recognition settings", "視覚認識設定", "Ajustes de reconocimiento visual", "Impostazioni riconoscimento visivo", "Stillingar sjóngreiningar", "Configurationes recognitionis visualis"),
    "多尺度匹配": _row("多尺度匹配", "Multi-scale matching", "マルチスケール照合", "Coincidencia multiescala", "Corrispondenza multiscala", "Margkvarðasamsvörun", "Concordantia multiscalaris"),
    "连续帧确认": _row("连续帧确认", "Consecutive-frame confirmation", "連続フレーム確認", "Confirmación de fotogramas consecutivos", "Conferma fotogrammi consecutivi", "Staðfesting samfelldra ramma", "Confirmatio quadrorum continuorum"),
    "等待识别": _row("等待识别", "Wait for recognition", "認識を待機", "Esperar reconocimiento", "Attendi riconoscimento", "Bíða eftir greiningu", "Recognitionem exspecta"),
    "最大等待": _row("最大等待", "Maximum wait", "最大待機", "Espera máxima", "Attesa massima", "Hámarksbið", "Mora maxima"),
    "循环体": _row("循环体", "Loop body", "ループ本体", "Cuerpo del bucle", "Corpo del ciclo", "Lykkjubolur", "Corpus iterationis"),
    "循环设置": _row("循环设置", "Loop settings", "ループ設定", "Ajustes del bucle", "Impostazioni ciclo", "Lykkjustillingar", "Configurationes iterationis"),
    "新建锚点模板": _row("新建锚点模板", "New anchor template", "新規アンカーテンプレート", "Nueva plantilla de ancla", "Nuovo modello ancora", "Nýtt akkerissniðmát", "Novum exemplar ancorae"),
    "锚点模板名称：": _row("锚点模板名称：", "Anchor template name:", "アンカーテンプレート名：", "Nombre de la plantilla de ancla:", "Nome modello ancora:", "Heiti akkerissniðmáts:", "Nomen exemplaris ancorae:"),
    "搜索模板名称…": _row("搜索模板名称…", "Search template names…", "テンプレート名を検索…", "Buscar nombres de plantilla…", "Cerca nomi modello…", "Leita í sniðmátanöfnum…", "Nomina exemplarium quaere…"),
    "选择": _row("选择", "Select", "選択", "Seleccionar", "Seleziona", "Velja", "Elige"),
    "未选择": _row("未选择", "Not selected", "未選択", "Sin seleccionar", "Non selezionato", "Ekki valið", "Non selectum"),
    "选择扫描模板": _row("选择扫描模板", "Choose scan template", "走査テンプレートを選択", "Elegir plantilla de escaneo", "Scegli modello di scansione", "Velja skönnunarsniðmát", "Exemplar explorationis elige"),
    "没有匹配的模板": _row("没有匹配的模板", "No matching templates", "一致するテンプレートがありません", "No hay plantillas coincidentes", "Nessun modello corrispondente", "Engin samsvarandi sniðmát", "Nulla exemplaria concordant"),
    "项目名称：": _row("项目名称：", "Project name:", "プロジェクト名：", "Nombre del proyecto:", "Nome progetto:", "Heiti verkefnis:", "Nomen projecti:"),
    "项目：": _row("项目：", "Project:", "プロジェクト：", "Proyecto:", "Progetto:", "Verkefni:", "Projectum:"),
    "模板名称：": _row("模板名称：", "Template name:", "テンプレート名：", "Nombre de plantilla:", "Nome modello:", "Heiti sniðmáts:", "Nomen exemplaris:"),
    "已保存": _row("已保存", "Saved", "保存しました", "Guardado", "Salvato", "Vistað", "Servatum"),
    "没有可执行模块": _row("没有可执行模块", "No executable modules", "実行可能なモジュールがありません", "No hay módulos ejecutables", "Nessun modulo eseguibile", "Engar keyranlegar einingar", "Nulli moduli exsequendi"),
    "没有可运行的起始模块。": _row("没有可运行的起始模块。", "No runnable Start module.", "実行可能な開始モジュールがありません。", "No hay un módulo de inicio ejecutable.", "Nessun modulo Start eseguibile.", "Engin keyranleg upphafseining.", "Nullus modulus initialis exsequi potest."),

    # Dynamic reusable fragments
    "Windows虚拟桌面": _row("Windows虚拟桌面", "Windows virtual desktop", "Windows 仮想デスクトップ", "Escritorio virtual de Windows", "Desktop virtuale Windows", "Windows sýndarskjáborð", "Desktop virtuale Windows"),
    "原点": _row("原点", "origin", "原点", "origen", "origine", "upphaf", "origo"),
    "全屏坐标": _row("全屏坐标", "Fullscreen coordinates", "全画面座標", "Coordenadas de pantalla completa", "Coordinate schermo intero", "Heildarskjáhnit", "Coordinatae totius scrinii"),
    "Windows物理坐标": _row("Windows物理坐标", "Windows physical coordinates", "Windows 物理座標", "Coordenadas físicas de Windows", "Coordinate fisiche Windows", "Windows-raunhnit", "Coordinatae physicae Windows"),
    "Windows全局": _row("Windows全局", "Windows global", "Windows グローバル", "Global de Windows", "Globale Windows", "Windows hnattrænt", "Windows globale"),
    "全局": _row("全局", "Global", "グローバル", "Global", "Globale", "Hnattrænt", "Globale"),
    "相对": _row("相对", "Relative", "相対", "Relativo", "Relativo", "Afstætt", "Relativum"),
    "已加载当前项目模板库：": _row("已加载当前项目模板库：", "Loaded current project template library: ", "現在のプロジェクトのテンプレートライブラリを読み込みました：", "Biblioteca de plantillas del proyecto cargada: ", "Libreria modelli del progetto caricata: ", "Sniðmátasafn verkefnis hlaðið: ", "Bibliotheca exemplarium projecti onerata: "),
    "个模板。默认使用全屏坐标。": _row("个模板。默认使用全屏坐标。", " templates. Fullscreen coordinates are used by default.", " 個。既定では全画面座標を使用します。", " plantillas. Se usan coordenadas de pantalla completa por defecto.", " modelli. Per impostazione predefinita si usano coordinate a schermo intero.", " sniðmát. Heildarskjáhnit eru notuð sjálfgefið.", " exemplaria. Coordinatae totius scrinii praedefinite adhibentur."),
    "锚点：": _row("锚点：", "Anchor: ", "アンカー：", "Ancla: ", "Ancora: ", "Akkeri: ", "Ancora: "),
    "锚点:": _row("锚点:", "Anchor:", "アンカー:", "Ancla:", "Ancora:", "Akkeri:", "Ancora:"),
    "正在等待识别": _row("正在等待识别", "waiting for recognition", "認識待機中", "esperando reconocimiento", "in attesa del riconoscimento", "bíður eftir greiningu", "recognitionem exspectans"),
    "按 K 记录": _row("按 K 记录", "press K to record", "K で記録", "pulsa K para registrar", "premi K per registrare", "ýttu K til að skrá", "preme K ut registres"),
    "已记录": _row("已记录", "Recorded", "記録済み", "Registrado", "Registrato", "Skráð", "Registratum"),
    "按 K 可继续记录": _row("按 K 可继续记录", "press K to keep recording", "K で続けて記録", "pulsa K para seguir registrando", "premi K per continuare a registrare", "ýttu K til að halda áfram", "preme K ut pergat registratio"),
    "已复制": _row("已复制", "Copied", "コピーしました", "Copiado", "Copiato", "Afritað", "Copiatum"),
    "条记录，可直接粘贴到 Excel。": _row("条记录，可直接粘贴到 Excel。", " records; paste directly into Excel.", " 件の記録。Excel に直接貼り付けできます。", " registros; se pueden pegar directamente en Excel.", " record; incollabili direttamente in Excel.", " færslur; má líma beint í Excel.", " registrationes; directe in Excel inseri possunt."),
    "区域：": _row("区域：", "Region: ", "領域：", "Región: ", "Regione: ", "Svæði: ", "Regio: "),
    "像素：": _row("像素：", "Pixels: ", "ピクセル：", "Píxeles: ", "Pixel: ", "Dílar: ", "Pixela: "),
    "不同颜色：": _row("不同颜色：", "Distinct colors: ", "色数：", "Colores distintos: ", "Colori distinti: ", "Mismunandi litir: ", "Colores distincti: "),
    "坐标输出": _row("坐标输出", "coordinate output", "座標出力", "salida de coordenadas", "uscita coordinate", "hnit úttak", "exitus coordinatarum"),
    "单数字输出": _row("单数字输出", "number output", "数値出力", "salida numérica", "uscita numerica", "töluúttak", "exitus numeri"),
    "键盘输入  文本：": _row("键盘输入  文本：", "Keyboard input  Text: ", "キーボード入力  テキスト：", "Entrada de teclado  Texto: ", "Input tastiera  Testo: ", "Lyklaborðsinntak  Texti: ", "Ingressus claviaturae  Textus: "),
    "固定坐标": _row("固定坐标", "Fixed coordinate", "固定座標", "Coordenada fija", "Coordinata fissa", "Fast hnit", "Coordinata fixa"),
    "锚点全局": _row("锚点全局", "anchor global", "アンカーのグローバル座標", "global del ancla", "globale ancora", "hnattrænt akkeri", "ancora globalis"),
    "运行完成": _row("运行完成", "Run complete", "実行完了", "Ejecución completada", "Esecuzione completata", "Keyrslu lokið", "Executio completa"),
    "已持续启用": _row("已持续启用", "enabled continuously", "継続的に有効", "activado continuamente", "abilitato continuamente", "virkt samfellt", "continue activatum"),
    "控制台 ready. Type 'help' for commands.": _row("控制台 ready. Type 'help' for commands.", "Console ready. Type 'help' for commands.", "コンソール準備完了。'help' でコマンド一覧を表示します。", "Consola lista. Escribe 'help' para ver los comandos.", "Console pronta. Digita 'help' per i comandi.", "Stjórnborð tilbúið. Sláðu inn 'help' fyrir skipanir.", "Consola parata. Scribe 'help' ad mandata."),
})


# ---------------------------------------------------------------------------
# Runtime translation helpers
# ---------------------------------------------------------------------------
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _translate_dynamic_chinese(
    raw: str,
    language: str,
) -> str:
    """
    Translate a Chinese source string containing runtime values.

    Example:
        固定坐标（坐标输出）  锚点:world.png  (12, 30)

    Exact translations are preferred.  If no exact entry exists, known source
    fragments are replaced longest-first while coordinates, filenames, paths,
    numbers and symbols are preserved verbatim.
    """
    translated = raw

    sources = sorted(
        _TRANSLATIONS.keys(),
        key=len,
        reverse=True,
    )

    for source in sources:
        if (
            source
            and source in translated
        ):
            row = _TRANSLATIONS[source]
            target = row.get(
                language,
                row.get(
                    "en",
                    source,
                ),
            )

            if target:
                translated = translated.replace(
                    source,
                    target,
                )

    return translated


# ---------------------------------------------------------------------------
# Dialogs, descriptions and runtime status text
# ---------------------------------------------------------------------------
_TRANSLATIONS.update({
    "UVAF started": _row("UVAF started", "UVAF started", "UVAF 起動", "UVAF iniciado", "UVAF avviato", "UVAF ræst", "UVAF initum"),
    "A shell command is already running.": _row("A shell command is already running.", "A shell command is already running.", "シェルコマンドはすでに実行中です。", "Ya hay un comando de shell en ejecución.", "È già in esecuzione un comando shell.", "Skeljarskipun er þegar í gangi.", "Mandatum shell iam currit."),

    "仅识别锚点设置": _row("仅识别锚点设置", "Anchor-only recognition settings", "アンカー限定認識設定", "Ajustes de reconocimiento limitado al ancla", "Impostazioni riconoscimento limitato all'ancora", "Stillingar greiningar við akkeri", "Configurationes recognitionis ad ancoram"),
    "锚点模板": _row("锚点模板", "Anchor template", "アンカーテンプレート", "Plantilla de ancla", "Modello ancora", "Akkerissniðmát", "Exemplar ancorae"),
    "连接在起始执行链中后，会直接限制 Recognition Engine 的全局可视范围；ROI 坐标相对于锚点中心。": _row(
        "连接在起始执行链中后，会直接限制 Recognition Engine 的全局可视范围；ROI 坐标相对于锚点中心。",
        "When connected to a Start chain, this directly restricts the Recognition Engine's global field of view; ROI coordinates are relative to the anchor center.",
        "開始チェーンに接続すると Recognition Engine のグローバル視野を直接制限します。ROI 座標はアンカー中心を基準にします。",
        "Al conectarse a una cadena de inicio, limita directamente el campo de visión global de Recognition Engine; las coordenadas ROI son relativas al centro del ancla.",
        "Collegato a una catena Start, limita direttamente il campo visivo globale di Recognition Engine; le coordinate ROI sono relative al centro dell'ancora.",
        "Tengt við Start-keðju takmarkar þetta beint heildarsjónsvið Recognition Engine; ROI-hnit miðast við miðju akkerisins.",
        "Catenae Start conexum, campum visus globalem Recognition Engine directe restringit; coordinatae ROI ad centrum ancorae referuntur."
    ),
    "尚未选择锚点": _row("尚未选择锚点", "No anchor selected", "アンカー未選択", "No se ha seleccionado un ancla", "Nessuna ancora selezionata", "Ekkert akkeri valið", "Nulla ancora selecta"),
    "请先选择锚点模板。": _row("请先选择锚点模板。", "Choose an anchor template first.", "先にアンカーテンプレートを選択してください。", "Selecciona primero una plantilla de ancla.", "Seleziona prima un modello ancora.", "Veldu fyrst akkerissniðmát.", "Primum exemplar ancorae elige."),
    "锚点识别失败": _row("锚点识别失败", "Anchor recognition failed", "アンカー認識に失敗", "Falló el reconocimiento del ancla", "Riconoscimento ancora non riuscito", "Greining akkeris mistókst", "Recognitio ancorae defecit"),
    "当前屏幕中没有找到所选锚点模板。": _row("当前屏幕中没有找到所选锚点模板。", "The selected anchor template was not found on the current screen.", "現在の画面で選択したアンカーテンプレートが見つかりません。", "No se encontró la plantilla de ancla seleccionada en la pantalla actual.", "Il modello ancora selezionato non è stato trovato sullo schermo corrente.", "Valið akkerissniðmát fannst ekki á núverandi skjá.", "Exemplar ancorae selectum in scrinio praesenti non inventum est."),
    "缺少锚点": _row("缺少锚点", "Missing anchor", "アンカーがありません", "Falta el ancla", "Ancora mancante", "Akkeri vantar", "Ancora deest"),
    "请选择锚点模板。": _row("请选择锚点模板。", "Choose an anchor template.", "アンカーテンプレートを選択してください。", "Selecciona una plantilla de ancla.", "Seleziona un modello ancora.", "Veldu akkerissniðmát.", "Exemplar ancorae elige."),
    "选择其他文件…": _row("选择其他文件…", "Choose another file…", "別のファイルを選択…", "Elegir otro archivo…", "Scegli un altro file…", "Velja aðra skrá…", "Alium fasciculum elige…"),

    "彩色 Ccoeff": _row("彩色 Ccoeff", "Color Ccoeff", "カラー Ccoeff", "Ccoeff en color", "Ccoeff colore", "Lita-Ccoeff", "Ccoeff coloratum"),
    "灰度匹配": _row("灰度匹配", "Grayscale matching", "グレースケール照合", "Coincidencia en escala de grises", "Corrispondenza in scala di grigi", "Grátónasamsvörun", "Concordantia scalae cinereae"),
    "边缘匹配": _row("边缘匹配", "Edge matching", "エッジ照合", "Coincidencia de bordes", "Corrispondenza bordi", "Jaðarsamsvörun", "Concordantia marginum"),
    "彩色 Ccoeff：比较模板与画面的整体像素结构。速度快，适合尺寸和方向基本不变的 UI，是常用的基础模板匹配。": _row(
        "彩色 Ccoeff：比较模板与画面的整体像素结构。速度快，适合尺寸和方向基本不变的 UI，是常用的基础模板匹配。",
        "Color Ccoeff compares the overall pixel structure of the template and frame. It is fast and works well for UI elements whose size and orientation remain stable.",
        "カラー Ccoeff はテンプレートと画面の全体的な画素構造を比較します。高速で、サイズや向きがほぼ変わらない UI に適しています。",
        "Color Ccoeff compara la estructura global de píxeles de la plantilla y la imagen. Es rápido y adecuado para interfaces cuyo tamaño y orientación apenas cambian.",
        "Color Ccoeff confronta la struttura complessiva dei pixel di modello e immagine. È veloce e adatto a UI con dimensioni e orientamento stabili.",
        "Lita-Ccoeff ber saman heildarpixlauppbyggingu sniðmáts og ramma. Það er hratt og hentar UI sem breytir lítið stærð eða stefnu.",
        "Color Ccoeff structuram pixelorum exemplaris et imaginis comparat. Celer est et UI magnitudine directioneque stabili aptus."
    ),
    "灰度匹配：先忽略颜色，只比较亮度与形状结构。适合颜色会变化、但明暗轮廓较稳定的目标。": _row(
        "灰度匹配：先忽略颜色，只比较亮度与形状结构。适合颜色会变化、但明暗轮廓较稳定的目标。",
        "Grayscale matching ignores color and compares brightness and shape structure. It is useful when colors vary but luminance contours stay stable.",
        "グレースケール照合は色を無視し、明るさと形状構造を比較します。色が変化しても明暗の輪郭が安定している対象に適します。",
        "La coincidencia en escala de grises ignora el color y compara brillo y forma. Es útil cuando cambia el color pero se mantiene el contorno de luminancia.",
        "La corrispondenza in scala di grigi ignora il colore e confronta luminosità e forma. È utile quando i colori cambiano ma i contorni restano stabili.",
        "Grátónasamsvörun hunsar lit og ber saman birtu og lögun. Hún hentar þegar litir breytast en birtuútlínur haldast stöðugar.",
        "Concordantia cinerea colorem neglegit et claritatem formamque comparat. Aptum est cum colores mutantur sed lineamenta luminis manent."
    ),
    "RGBCount：强调模板与候选区域的 RGB 颜色一致程度。适合颜色固定、需要排除形状相似但颜色不同目标的场景。": _row(
        "RGBCount：强调模板与候选区域的 RGB 颜色一致程度。适合颜色固定、需要排除形状相似但颜色不同目标的场景。",
        "RGBCount emphasizes RGB color agreement between the template and candidate region. It is useful when color is stable and similarly shaped targets must be rejected.",
        "RGBCount はテンプレートと候補領域の RGB 色一致度を重視します。色が安定し、形は似ていても色が異なる対象を除外したい場合に適します。",
        "RGBCount da prioridad a la coincidencia de color RGB entre plantilla y región candidata. Es útil cuando el color es estable y hay que descartar objetivos de forma similar.",
        "RGBCount privilegia la corrispondenza dei colori RGB tra modello e regione candidata. È utile quando il colore è stabile e occorre escludere bersagli dalla forma simile.",
        "RGBCount leggur áherslu á RGB-litasamsvörun milli sniðmáts og svæðis. Hentar þegar litur er stöðugur og útiloka þarf svipuð form með öðrum lit.",
        "RGBCount concordantiam colorum RGB inter exemplar et regionem candidatum extollit. Aptum est cum color stabilis est et formae similes coloribus diversis excludendae sunt."
    ),
    "HSVCount：在色相、饱和度和亮度空间比较颜色。通常比直接 RGB 更能容忍一定的明暗变化。": _row(
        "HSVCount：在色相、饱和度和亮度空间比较颜色。通常比直接 RGB 更能容忍一定的明暗变化。",
        "HSVCount compares colors in hue, saturation and value space and generally tolerates lighting changes better than direct RGB comparison.",
        "HSVCount は色相・彩度・明度空間で色を比較し、通常は RGB 直接比較より明暗変化に強くなります。",
        "HSVCount compara los colores en tono, saturación y valor y suele tolerar mejor los cambios de iluminación que RGB directo.",
        "HSVCount confronta i colori nello spazio tonalità, saturazione e valore e in genere tollera meglio i cambi di luminosità rispetto a RGB diretto.",
        "HSVCount ber saman litblæ, mett­un og birtu og þolir yfirleitt birtubreytingar betur en bein RGB-samanburður.",
        "HSVCount colores in spatio toni, saturationis et valoris comparat atque mutationes luminis melius quam RGB directum tolerat."
    ),
    "边缘匹配：提取轮廓后再进行匹配，弱化颜色和内部纹理影响。适合轮廓明显的目标；边缘过少的模板会被引擎自动保护性过滤。": _row(
        "边缘匹配：提取轮廓后再进行匹配，弱化颜色和内部纹理影响。适合轮廓明显的目标；边缘过少的模板会被引擎自动保护性过滤。",
        "Edge matching extracts contours before matching, reducing the influence of color and internal texture. It works well for clearly outlined targets; templates with too few edges are filtered for safety.",
        "エッジ照合は輪郭を抽出してから比較し、色や内部テクスチャの影響を弱めます。輪郭が明確な対象に適し、エッジが少なすぎるテンプレートは自動的に除外されます。",
        "La coincidencia de bordes extrae contornos antes de comparar, reduciendo la influencia del color y la textura interna. Funciona bien con objetivos de contorno claro; las plantillas con pocos bordes se filtran automáticamente.",
        "La corrispondenza dei bordi estrae i contorni prima del confronto, riducendo l'influenza di colore e texture. È adatta a bersagli ben delineati; i modelli con pochi bordi vengono filtrati automaticamente.",
        "Jaðarsamsvörun dregur út útlínur áður en borið er saman og minnkar áhrif lita og áferðar. Hentar skýrum útlínum; sniðmát með of fáa jaðra eru sjálfvirkt síuð.",
        "Concordantia marginum lineamenta prius extrahit, colorem texturamque internam minuens. Formis clare delineatis apta est; exemplaria marginibus paucis automatice excluduntur."
    ),
    "FeatureMatch：提取局部特征点并进行描述子匹配，再用 RANSAC/Homography 验证几何关系。更能适应缩放、旋转和部分透视变化，但通常比普通模板匹配更慢。": _row(
        "FeatureMatch：提取局部特征点并进行描述子匹配，再用 RANSAC/Homography 验证几何关系。更能适应缩放、旋转和部分透视变化，但通常比普通模板匹配更慢。",
        "FeatureMatch extracts local keypoints, matches descriptors, then verifies geometry with RANSAC/Homography. It handles scale, rotation and some perspective changes better, but is usually slower than standard template matching.",
        "FeatureMatch は局所特徴点と記述子を照合し、RANSAC/Homography で幾何関係を検証します。拡大縮小・回転・一部の透視変化に強い一方、通常のテンプレート照合より遅くなります。",
        "FeatureMatch extrae puntos locales, compara descriptores y valida la geometría con RANSAC/Homography. Tolera mejor escala, rotación y cierta perspectiva, pero suele ser más lento.",
        "FeatureMatch estrae punti locali, confronta descrittori e verifica la geometria con RANSAC/Homography. Gestisce meglio scala, rotazione e prospettiva, ma in genere è più lento.",
        "FeatureMatch finnur staðbundna eiginleikapunkta, ber saman lýsara og staðfestir rúmfræði með RANSAC/Homography. Það þolir betur kvarða, snúning og sjónarhorn en er yfirleitt hægara.",
        "FeatureMatch puncta proprietatum extrahit, descriptoribus comparatis, geometriam RANSAC/Homography probat. Mutationes scalae, rotationis et perspectivae melius tolerat, sed plerumque tardius est."
    ),

    "X 和 Y 必须显式带正负号，例如 X=+20、Y=-15。模块会把这两个偏移量加到输入坐标后再输出。": _row(
        "X 和 Y 必须显式带正负号，例如 X=+20、Y=-15。模块会把这两个偏移量加到输入坐标后再输出。",
        "X and Y must include an explicit sign, e.g. X=+20 and Y=-15. The module adds these offsets to the input coordinate and outputs the result.",
        "X と Y には X=+20、Y=-15 のように符号を明示してください。入力座標にこのオフセットを加算して出力します。",
        "X e Y deben llevar signo explícito, por ejemplo X=+20 e Y=-15. El módulo suma estos desplazamientos a la coordenada de entrada.",
        "X e Y devono includere il segno, ad esempio X=+20 e Y=-15. Il modulo aggiunge questi offset alla coordinata in ingresso.",
        "X og Y verða að hafa skýrt formerki, t.d. X=+20 og Y=-15. Einingin bætir hliðruninni við inntakshnitið.",
        "X et Y signum explicitum habere debent, ut X=+20 et Y=-15. Modulus hos discessus coordinatae ingressae addit."
    ),
    "坐标偏移格式错误": _row("坐标偏移格式错误", "Invalid coordinate offset format", "座標オフセット形式エラー", "Formato de desplazamiento no válido", "Formato offset coordinata non valido", "Ógilt snið hnitahliðrunar", "Forma discessus coordinatae invalida"),
    "普通模式：读取上一个模块输出的坐标，并将鼠标瞬移到该精确坐标。": _row(
        "普通模式：读取上一个模块输出的坐标，并将鼠标瞬移到该精确坐标。",
        "Normal mode reads the coordinate output of the previous module and instantly moves the mouse to that exact point.",
        "通常モードでは前のモジュールの座標出力を読み取り、その正確な位置へマウスを瞬時に移動します。",
        "El modo normal lee la coordenada del módulo anterior y mueve instantáneamente el ratón a ese punto exacto.",
        "La modalità normale legge la coordinata del modulo precedente e sposta istantaneamente il mouse sul punto esatto.",
        "Venjulegur hamur les hnit frá fyrri einingu og færir músina samstundis á nákvæman punkt.",
        "Modus ordinarius coordinatam moduli prioris legit et murem statim ad punctum exactum movet."
    ),
    "高级移动": _row("高级移动", "Advanced movement", "詳細移動", "Movimiento avanzado", "Movimento avanzato", "Ítarleg færsla", "Motus provectus"),
    "坐标偏移（允许正负值）": _row("坐标偏移（允许正负值）", "Coordinate offset (signed values allowed)", "座標オフセット（正負可）", "Desplazamiento de coordenadas (se permiten signos)", "Offset coordinate (valori con segno)", "Hnitahliðrun (jákvæð/neikvæð gildi)", "Discessus coordinatarum (signa permissa)"),
    "最终 X = 输入 X + 右 − 左；最终 Y = 输入 Y + 下 − 上。四项自身仍允许填写负数。": _row(
        "最终 X = 输入 X + 右 − 左；最终 Y = 输入 Y + 下 − 上。四项自身仍允许填写负数。",
        "Final X = input X + right − left; final Y = input Y + down − up. All four fields may themselves contain negative values.",
        "最終 X = 入力 X + 右 − 左、最終 Y = 入力 Y + 下 − 上。4項目には負数も入力できます。",
        "X final = X de entrada + derecha − izquierda; Y final = Y de entrada + abajo − arriba. Los cuatro campos también admiten valores negativos.",
        "X finale = X ingresso + destra − sinistra; Y finale = Y ingresso + giù − su. Tutti e quattro i campi accettano anche valori negativi.",
        "Loka-X = inntaks-X + hægri − vinstri; loka-Y = inntaks-Y + niður − upp. Öll fjögur gildi mega einnig vera neikvæð.",
        "X finale = X ingressum + dextera − sinistra; Y finale = Y ingressum + deorsum − sursum. Omnia quattuor campi valores negativos accipiunt."
    ),
    "移速模式": _row("移速模式", "Movement speed mode", "移動速度モード", "Modo de velocidad", "Modalità velocità", "Hraðahamur", "Modus velocitatis"),
    "规定时间到达（秒）": _row("规定时间到达（秒）", "Arrive in specified time (seconds)", "指定時間で到達（秒）", "Llegar en tiempo especificado (s)", "Arriva nel tempo specificato (s)", "Ná á tilteknum tíma (sek.)", "Adveni tempore definito (sec.)"),
    "像素每秒": _row("像素每秒", "Pixels per second", "ピクセル/秒", "Píxeles por segundo", "Pixel al secondo", "Dílar á sekúndu", "Pixela per secundum"),
    "移速偏移 ±": _row("移速偏移 ±", "Speed variation ±", "速度変動 ±", "Variación de velocidad ±", "Variazione velocità ±", "Hraðafrávik ±", "Variatio velocitatis ±"),
    "随机移动路线": _row("随机移动路线", "Random movement path", "ランダム移動経路", "Ruta de movimiento aleatoria", "Percorso casuale", "Handahófsleið", "Iter motus fortuitum"),
    "启用后会随机生成平滑曲线路径；仍会严格落在最终目标点。像素/秒模式会按实际曲线路径长度计算时间。": _row(
        "启用后会随机生成平滑曲线路径；仍会严格落在最终目标点。像素/秒模式会按实际曲线路径长度计算时间。",
        "When enabled, a smooth random curve is generated while still landing exactly on the final target. Pixels-per-second mode calculates duration from the actual curve length.",
        "有効にすると滑らかなランダム曲線経路を生成しつつ、最終目標点には正確に到達します。ピクセル/秒モードでは実際の曲線長から時間を計算します。",
        "Al activarlo se genera una curva aleatoria suave, pero se termina exactamente en el objetivo. El modo píxeles/segundo calcula el tiempo según la longitud real de la curva.",
        "Se attivo, genera un percorso curvo casuale e fluido terminando comunque esattamente sul bersaglio. La modalità pixel/secondo calcola il tempo dalla lunghezza reale della curva.",
        "Þegar virkt er myndast slétt handahófsbogaleið sem endar samt nákvæmlega á markpunkti. Dílar/sek. reiknar tíma út frá raunlengd leiðarinnar.",
        "Cum activum est, iter curvum fortuitum et leve generatur, sed punctum finale exacte attingitur. Modus pixelorum/secundum tempus ex longitudine vera itineris computat."
    ),
    "像素/秒：根据实际移动路线长度计算所需时间。": _row("像素/秒：根据实际移动路线长度计算所需时间。", "Pixels/s: calculate duration from the actual movement-path length.", "ピクセル/秒：実際の移動経路長から所要時間を計算します。", "Píxeles/s: calcula la duración según la longitud real de la ruta.", "Pixel/s: calcola la durata dalla lunghezza effettiva del percorso.", "Dílar/sek.: reiknar tíma út frá raunlengd leiðarinnar.", "Pixela/sec.: durationem ex longitudine itineris veri computat."),
    "秒：填写 0 即瞬移；大于 0 时会在规定时间内到达目标。": _row("秒：填写 0 即瞬移；大于 0 时会在规定时间内到达目标。", "Seconds: 0 means instant movement; values above 0 reach the target within the specified duration.", "秒：0 は瞬時移動、0 より大きい値では指定時間内に目標へ到達します。", "Segundos: 0 significa movimiento instantáneo; valores mayores que 0 llegan al objetivo en el tiempo indicado.", "Secondi: 0 significa spostamento istantaneo; valori maggiori di 0 raggiungono il bersaglio nel tempo indicato.", "Sekúndur: 0 þýðir tafarlaus færsla; stærra en 0 nær markinu á tilteknum tíma.", "Secunda: 0 motum instantaneum significat; valor maior quam 0 scopum tempore definito attingit."),

    "点击次数": _row("点击次数", "Click count", "クリック回数", "Número de clics", "Numero di clic", "Fjöldi smella", "Numerus pressionum"),
    "“点击”始终表示一次完整的按下→松开动作，与以后单独的“按下”和“松开”模块区分。": _row(
        "“点击”始终表示一次完整的按下→松开动作，与以后单独的“按下”和“松开”模块区分。",
        "“Click” always means one complete press→release action, distinct from separate future Press and Release modules.",
        "「クリック」は常に押下→解放の1回の完全な操作を意味し、今後の個別の「押下」「解放」モジュールとは区別されます。",
        "«Clic» siempre significa una acción completa pulsar→soltar, distinta de futuros módulos separados de pulsar y soltar.",
        "«Clic» indica sempre un'azione completa pressione→rilascio, distinta dai futuri moduli separati Premi e Rilascia.",
        "„Smellur“ merkir alltaf eina heila ýta→sleppa aðgerð, aðskilda frá framtíðar einingum fyrir ýtingu og sleppingu.",
        "«Preme» semper actionem integram premere→dimittere significat, distinctam a futuris modulis separatis."
    ),
    "高级点击": _row("高级点击", "Advanced click", "詳細クリック", "Clic avanzado", "Clic avanzato", "Ítarlegur smellur", "Pressio provecta"),
    "每次按下时长": _row("每次按下时长", "Press duration", "押下時間", "Duración de pulsación", "Durata pressione", "Lengd ýtingar", "Duratio pressionis"),
    "两次点击间隔": _row("两次点击间隔", "Interval between clicks", "クリック間隔", "Intervalo entre clics", "Intervallo tra clic", "Bil milli smella", "Intervallum inter pressiones"),
    "起始点与结束点": _row("起始点与结束点", "Start and end points", "開始点と終了点", "Puntos inicial y final", "Punti iniziale e finale", "Upphafs- og endapunktur", "Puncta initii et finis"),
    "起始 X": _row("起始 X", "Start X", "開始 X", "X inicial", "X iniziale", "Upphaf X", "X initiale"),
    "结束 X": _row("结束 X", "End X", "終了 X", "X final", "X finale", "Enda X", "X finale"),
    "起始点按下等待": _row("起始点按下等待", "Hold at start before moving", "開始点での押下待機", "Espera pulsada en el inicio", "Attesa premuta al punto iniziale", "Bið niðri á upphafspunkti", "Mora premendi in puncto initiali"),

    "录制按键": _row("录制按键", "Record key", "キーを記録", "Grabar tecla", "Registra tasto", "Taka upp lykil", "Clavem registra"),
    "请按下任意键": _row("请按下任意键", "Press any key", "任意のキーを押してください", "Pulsa cualquier tecla", "Premi un tasto", "Ýttu á hvaða lykil sem er", "Quamlibet clavem preme"),
    "按下后会立即记录并关闭此窗口。Esc 也可以被记录。": _row("按下后会立即记录并关闭此窗口。Esc 也可以被记录。", "The key is recorded immediately and this window closes. Esc can also be recorded.", "キーを押すとすぐに記録され、このウィンドウは閉じます。Esc も記録できます。", "La tecla se registra inmediatamente y esta ventana se cierra. Esc también se puede registrar.", "Il tasto viene registrato subito e la finestra si chiude. È possibile registrare anche Esc.", "Lykillinn skráist strax og glugginn lokast. Esc má einnig skrá.", "Clavis statim registratur et fenestra clauditur. Esc quoque registrari potest."),
    "输入文本": _row("输入文本", "Enter text", "テキスト入力", "Introducir texto", "Inserisci testo", "Slá inn texta", "Textum insere"),
    "按键模式": _row("按键模式", "Key mode", "キーモード", "Modo tecla", "Modalità tasto", "Lyklahamur", "Modus clavis"),
    "当前按键": _row("当前按键", "Current key", "現在のキー", "Tecla actual", "Tasto corrente", "Núverandi lykill", "Clavis praesens"),
    "按下": _row("按下", "Press", "押下", "Pulsar", "Premi", "Ýta", "Preme"),
    "长按": _row("长按", "Hold", "長押し", "Mantener", "Tieni premuto", "Halda", "Retine"),
    "两次间隔": _row("两次间隔", "Interval", "間隔", "Intervalo", "Intervallo", "Bil", "Intervallum"),
    "长按时长": _row("长按时长", "Hold duration", "長押し時間", "Duración de pulsación", "Durata pressione lunga", "Lengd halds", "Duratio retentionis"),
    "文本输入": _row("文本输入", "Text input", "テキスト入力", "Entrada de texto", "Input testo", "Textainntak", "Ingressus textus"),
    "输入任意文本；运行时将按原内容输入。": _row("输入任意文本；运行时将按原内容输入。", "Enter any text; it will be typed exactly as provided at runtime.", "任意のテキストを入力できます。実行時にその内容をそのまま入力します。", "Introduce cualquier texto; durante la ejecución se escribirá exactamente.", "Inserisci qualsiasi testo; durante l'esecuzione verrà digitato così com'è.", "Sláðu inn hvaða texta sem er; hann verður sleginn inn óbreyttur við keyrslu.", "Quemlibet textum insere; tempore executionis eodem modo scribetur."),
    "文本模式支持 Unicode 文本。高级模式中的间隔偏移与模拟输入可用于随机化字符之间的节奏。": _row(
        "文本模式支持 Unicode 文本。高级模式中的间隔偏移与模拟输入可用于随机化字符之间的节奏。",
        "Text mode supports Unicode. In advanced mode, interval variation and simulated input can randomize the rhythm between characters.",
        "テキストモードは Unicode に対応します。詳細モードでは間隔変動と模擬入力で文字間のリズムをランダム化できます。",
        "El modo texto admite Unicode. En modo avanzado, la variación de intervalos y la entrada simulada pueden aleatorizar el ritmo entre caracteres.",
        "La modalità testo supporta Unicode. In modalità avanzata, variazione intervallo e input simulato possono randomizzare il ritmo tra caratteri.",
        "Textahamur styður Unicode. Í ítarlegum ham geta bilafrávik og hermt inntak handahófskennt takt milli stafa.",
        "Modus textus Unicode sustinet. In modo provecto variatio intervallorum et ingressus simulatus rhythmum inter litteras variare possunt."
    ),
    "高级键盘输入": _row("高级键盘输入", "Advanced keyboard input", "詳細キーボード入力", "Entrada de teclado avanzada", "Input tastiera avanzato", "Ítarlegt lyklaborðsinntak", "Ingressus claviaturae provectus"),
    "时长偏移 ±": _row("时长偏移 ±", "Duration variation ±", "時間変動 ±", "Variación de duración ±", "Variazione durata ±", "Tímalengdarfrávik ±", "Variatio durationis ±"),
    "间隔偏移 ±": _row("间隔偏移 ±", "Interval variation ±", "間隔変動 ±", "Variación de intervalo ±", "Variazione intervallo ±", "Bilfrávik ±", "Variatio intervalli ±"),
    "模拟键盘输入": _row("模拟键盘输入", "Simulate human keyboard input", "人間らしいキーボード入力を模擬", "Simular entrada humana de teclado", "Simula input tastiera umano", "Herma mannlegt lyklaborðsinntak", "Ingressum claviaturae humanum simula"),
    "模拟模式会在允许的偏移范围内随机化按下/松开与输入间隔，尽量接近真实用户的键盘节奏。": _row(
        "模拟模式会在允许的偏移范围内随机化按下/松开与输入间隔，尽量接近真实用户的键盘节奏。",
        "Simulation mode randomizes press/release timing and input intervals within the allowed variation to approximate a real user's typing rhythm.",
        "模擬モードでは許容範囲内で押下・解放時間と入力間隔をランダム化し、人間の入力リズムに近づけます。",
        "El modo simulado aleatoriza los tiempos de pulsación/soltado y los intervalos dentro del margen permitido para aproximarse al ritmo de un usuario real.",
        "La modalità simulata randomizza pressione/rilascio e intervalli entro la variazione consentita per avvicinarsi al ritmo di un utente reale.",
        "Hermihamur handahófskennir ýtingu/sleppingu og inntaksbil innan leyfilegra frávika til að líkja eftir raunverulegum notanda.",
        "Modus simulatus tempora premendi/dimittendi et intervalla intra variationem permissam fortuito mutat ut rhythmum usoris veri imitetur."
    ),

    "选择程序": _row("选择程序", "Choose program", "プログラムを選択", "Elegir programa", "Scegli programma", "Velja forrit", "Programma elige"),
    "计时": _row("计时", "Timer", "計時", "Temporizador", "Timer", "Tímamælir", "Temporarium"),
    "结束后行为": _row("结束后行为", "Action when time expires", "終了時の動作", "Acción al finalizar", "Azione alla scadenza", "Aðgerð við lok", "Actio tempore finito"),
    "结束进程": _row("结束进程", "Stop process", "プロセスを終了", "Finalizar proceso", "Termina processo", "Stöðva ferli", "Processum termina"),
    "结束进程并关闭程序": _row("结束进程并关闭程序", "Stop process and close application", "プロセスを終了してアプリを閉じる", "Finalizar proceso y cerrar aplicación", "Termina processo e chiudi applicazione", "Stöðva ferli og loka forriti", "Processum termina et programma claude"),
    "执行链": _row("执行链", "Execute chain", "チェーンを実行", "Ejecutar cadena", "Esegui catena", "Keyra keðju", "Catenam exsequere"),
    "终止其他事件链条并执行链": _row("终止其他事件链条并执行链", "Stop other event chains and execute chain", "他のイベントチェーンを停止してチェーンを実行", "Detener otras cadenas y ejecutar la cadena", "Ferma le altre catene ed esegui la catena", "Stöðva aðrar atburðakeðjur og keyra keðju", "Alias catenas eventuum siste et catenam exsequere"),
    "“执行链”会触发事件模块“时钟终止后链”。一个项目只允许放置一个该事件模块。": _row(
        "“执行链”会触发事件模块“时钟终止后链”。一个项目只允许放置一个该事件模块。",
        "“Execute chain” triggers the “Clock end chain” event module. Only one such event module may exist in a project.",
        "「チェーンを実行」はイベントモジュール「時計終了後チェーン」を起動します。1つのプロジェクトに配置できるのは1つだけです。",
        "«Ejecutar cadena» activa el módulo de evento «Cadena al terminar el reloj». Solo puede existir uno por proyecto.",
        "«Esegui catena» attiva il modulo evento «Catena dopo fine timer». Ne è consentito solo uno per progetto.",
        "„Keyra keðju“ virkjar atburðaeininguna „Keðja eftir klukkulok“. Aðeins ein slík eining má vera í verkefni.",
        "«Catenam exsequere» modulum eventus «Catena post horologium» excitat. Unus tantum talis modulus in projecto permittitur."
    ),
    "同一轮内部模块会严格按顺序完整执行；一轮完成后才会进入下一轮。": _row(
        "同一轮内部模块会严格按顺序完整执行；一轮完成后才会进入下一轮。",
        "Modules inside each iteration run strictly in order and must complete before the next iteration begins.",
        "各反復内のモジュールは厳密な順序で完了まで実行され、1回が完了してから次の反復へ進みます。",
        "Los módulos de cada iteración se ejecutan estrictamente en orden y deben terminar antes de comenzar la siguiente.",
        "I moduli di ogni iterazione vengono eseguiti rigorosamente in ordine e devono completarsi prima dell'iterazione successiva.",
        "Einingar innan hverrar ítrunar keyra strangt í röð og verða að klárast áður en næsta ítrun hefst.",
        "Moduli cuiusque iterationis ordine stricte exsequuntur et compleri debent ante iterationem sequentem."
    ),

    "模板": _row("模板", "Template", "テンプレート", "Plantilla", "Modello", "Sniðmát", "Exemplar"),
    "开启后，扫描模板会保持运行，直到识别到目标或达到最大等待时间；同一条链中的下一个模块不会提前执行。": _row(
        "开启后，扫描模板会保持运行，直到识别到目标或达到最大等待时间；同一条链中的下一个模块不会提前执行。",
        "When enabled, Scan Template remains running until the target is recognized or the maximum wait expires; the next module in the same chain cannot start early.",
        "有効にすると、対象を認識するか最大待機時間に達するまでテンプレート走査が実行中のままとなり、同じチェーンの次モジュールは先に開始できません。",
        "Al activarlo, Escanear plantilla sigue ejecutándose hasta reconocer el objetivo o alcanzar la espera máxima; el siguiente módulo de la misma cadena no puede adelantarse.",
        "Se attivo, Scansiona modello resta in esecuzione finché rileva il bersaglio o scade l'attesa massima; il modulo successivo della stessa catena non parte in anticipo.",
        "Þegar virkt er heldur skönnun áfram þar til mark finnst eða hámarksbið rennur út; næsta eining í sömu keðju getur ekki byrjað fyrr.",
        "Cum activum est, exploratio exemplaris currit donec scopum agnoscat vel mora maxima finiatur; modulus sequens eiusdem catenae ante tempus incipere non potest."
    ),
    "从本模块开始扫描起计算。目标一旦出现会立即完成，不会等待到上限。": _row("从本模块开始扫描起计算。目标一旦出现会立即完成，不会等待到上限。", "Measured from the moment this module starts scanning. It completes immediately when the target appears rather than waiting for the limit.", "このモジュールが走査を開始した時点から計測します。対象が現れたら上限まで待たず即座に完了します。", "Se mide desde que este módulo empieza a escanear. Termina en cuanto aparece el objetivo, sin esperar al límite.", "Si misura dall'inizio della scansione del modulo. Termina appena compare il bersaglio, senza attendere il limite.", "Mælt frá því einingin byrjar að skanna. Hún lýkur strax þegar markið birtist og bíður ekki til hámarks.", "Computatur ab initio explorationis huius moduli. Statim completur cum scopus apparet neque ad terminum exspectat."),
    "等待识别属于扫描模板模块本身的执行时间：目标出现后立即输出坐标并完成；超时仍未出现则本链停止。不同事件链不会因此互相等待。": _row(
        "等待识别属于扫描模板模块本身的执行时间：目标出现后立即输出坐标并完成；超时仍未出现则本链停止。不同事件链不会因此互相等待。",
        "Recognition waiting is part of the Scan Template module itself: it outputs the coordinate and completes as soon as the target appears; if the timeout expires first, this chain stops. Separate event chains do not wait for each other.",
        "認識待機はテンプレート走査モジュール自身の実行時間です。対象が現れれば座標を出力して完了し、タイムアウトまで現れなければそのチェーンを停止します。別のイベントチェーン同士は待ちません。",
        "La espera de reconocimiento forma parte del propio módulo Escanear plantilla: al aparecer el objetivo emite la coordenada y termina; si vence el tiempo, se detiene esa cadena. Las cadenas de eventos independientes no se esperan entre sí.",
        "L'attesa del riconoscimento fa parte del modulo Scansiona modello: appena compare il bersaglio emette la coordinata e termina; se scade il tempo, la catena si arresta. Le catene di eventi separate non si attendono.",
        "Bið eftir greiningu er hluti af skönnunareiningunni sjálfri: þegar mark birtist skilar hún hniti og lýkur; ef tíminn rennur út stöðvast keðjan. Aðskildar atburðakeðjur bíða ekki hver eftir annarri.",
        "Exspectatio recognitionis pars ipsius moduli explorationis est: cum scopus apparet coordinatam edit et completur; si tempus excurrit catena sistit. Catenae eventuum separatae invicem non exspectant."
    ),
    "识别方法（默认全部启用）": _row("识别方法（默认全部启用）", "Recognition methods (all enabled by default)", "認識方法（既定ですべて有効）", "Métodos de reconocimiento (todos activados por defecto)", "Metodi di riconoscimento (tutti attivi per impostazione predefinita)", "Greiningaraðferðir (allar virkar sjálfgefið)", "Methodi recognitionis (omnes praedefinite activae)"),
    "选择模板图片": _row("选择模板图片", "Choose template image", "テンプレート画像を選択", "Elegir imagen de plantilla", "Scegli immagine modello", "Velja sniðmátsmynd", "Imaginem exemplaris elige"),
    "加入模板库": _row("加入模板库", "Add to template library", "テンプレートライブラリに追加", "Añadir a la biblioteca de plantillas", "Aggiungi alla libreria modelli", "Bæta í sniðmátasafn", "Bibliothecae exemplarium adde"),
    "是否将这个模板加入当前项目的模板库？": _row("是否将这个模板加入当前项目的模板库？", "Add this template to the current project's template library?", "このテンプレートを現在のプロジェクトのライブラリに追加しますか？", "¿Añadir esta plantilla a la biblioteca del proyecto actual?", "Aggiungere questo modello alla libreria del progetto corrente?", "Bæta þessu sniðmáti í safn núverandi verkefnis?", "Hoc exemplar bibliothecae projecti praesentis addere?"),
    "至少选择一种识别方法": _row("至少选择一种识别方法", "Select at least one recognition method", "認識方法を1つ以上選択してください", "Selecciona al menos un método de reconocimiento", "Seleziona almeno un metodo di riconoscimento", "Veldu að minnsta kosti eina greiningaraðferð", "Unam saltem methodum recognitionis elige"),
    "扫描模板至少需要启用一种识别方法。": _row("扫描模板至少需要启用一种识别方法。", "Scan Template requires at least one recognition method.", "テンプレート走査には少なくとも1つの認識方法が必要です。", "Escanear plantilla necesita al menos un método de reconocimiento.", "Scansiona modello richiede almeno un metodo di riconoscimento.", "Sniðmátaskönnun þarf að minnsta kosti eina greiningaraðferð.", "Exploratio exemplaris unam saltem methodum recognitionis requirit."),

    "按住左键拖动框选区域 · Esc 取消": _row("按住左键拖动框选区域 · Esc 取消", "Hold left mouse button and drag to select · Esc to cancel", "左ボタンを押したままドラッグして選択 · Esc でキャンセル", "Mantén pulsado el botón izquierdo y arrastra · Esc para cancelar", "Tieni premuto il tasto sinistro e trascina · Esc per annullare", "Haltu vinstri músarhnappi og dragðu · Esc hættir við", "Sinistrum muris retine et trahe · Esc cancellat"),
    "ROI 设置": _row("ROI 设置", "ROI settings", "ROI 設定", "Ajustes ROI", "Impostazioni ROI", "ROI-stillingar", "Configurationes ROI"),
    "左上角坐标": _row("左上角坐标", "Top-left coordinate", "左上座標", "Coordenada superior izquierda", "Coordinata in alto a sinistra", "Efra vinstra hnit", "Coordinata superior sinistra"),
    "大小": _row("大小", "Size", "サイズ", "Tamaño", "Dimensione", "Stærð", "Magnitudo"),
    "格式错误": _row("格式错误", "Invalid format", "形式エラー", "Formato no válido", "Formato non valido", "Ógilt snið", "Forma invalida"),
    "当前屏幕中没有找到所选锚点。": _row("当前屏幕中没有找到所选锚点。", "The selected anchor was not found on the current screen.", "現在の画面で選択したアンカーが見つかりません。", "No se encontró el ancla seleccionada en la pantalla actual.", "L'ancora selezionata non è stata trovata sullo schermo corrente.", "Valið akkeri fannst ekki á núverandi skjá.", "Ancora selecta in scrinio praesenti non inventa est."),
    "输入正整数，或输入 ∞ / 无限": _row("输入正整数，或输入 ∞ / 无限", "Enter a positive integer, or ∞ / Infinite", "正の整数、または ∞ / 無限 を入力", "Introduce un entero positivo o ∞ / Infinito", "Inserisci un intero positivo o ∞ / Infinito", "Sláðu inn jákvæða heiltölu eða ∞ / Óendanlegt", "Numerum integrum positivum vel ∞ / Infinitum insere"),
    "无限": _row("无限", "Infinite", "無限", "Infinito", "Infinito", "Óendanlegt", "Infinitum"),
    "次": _row("次", "times", "回", "veces", "volte", "sinnum", "vicibus"),
    "⚠ 判定框含动作：会执行，但不直接参与判定": _row("⚠ 判定框含动作：会执行，但不直接参与判定", "⚠ Condition contains actions: they will execute but do not directly contribute to the condition", "⚠ 条件内にアクションがあります：実行されますが判定値には直接寄与しません", "⚠ La condición contiene acciones: se ejecutarán, pero no aportan directamente al resultado", "⚠ La condizione contiene azioni: verranno eseguite ma non contribuiscono direttamente al risultato", "⚠ Skilyrðið inniheldur aðgerðir: þær keyra en leggja ekki beint til niðurstöðunnar", "⚠ Condicio actiones continet: exsequentur sed iudicio directe non conferunt"),
    "循环次数：": _row("循环次数：", "Loop count: ", "ループ回数：", "Número de bucles: ", "Numero cicli: ", "Fjöldi lykkja: ", "Numerus iterationum: "),
    "循环次数：∞": _row("循环次数：∞", "Loop count: ∞", "ループ回数：∞", "Número de bucles: ∞", "Numero cicli: ∞", "Fjöldi lykkja: ∞", "Numerus iterationum: ∞"),

    "已导入": _row("已导入", "Imported", "インポート済み", "Importado", "Importato", "Flutt inn", "Importatum"),
    "已导出": _row("已导出", "Exported", "エクスポート済み", "Exportado", "Esportato", "Flutt út", "Exportatum"),
    "已创建模板": _row("已创建模板", "Created template", "テンプレート作成済み", "Plantilla creada", "Modello creato", "Sniðmát búið til", "Exemplar creatum"),
    "已创建自定义模块": _row("已创建自定义模块", "Created custom module", "カスタムモジュールを作成しました", "Módulo personalizado creado", "Modulo personalizzato creato", "Sérsniðin eining búin til", "Modulus consuetudinalis creatus"),
    "已放置自定义模块": _row("已放置自定义模块", "Placed custom module", "カスタムモジュールを配置しました", "Módulo personalizado colocado", "Modulo personalizzato posizionato", "Sérsniðin eining sett niður", "Modulus consuetudinalis positus"),
    "正在运行": _row("正在运行", "Running", "実行中", "Ejecutando", "In esecuzione", "Keyrir", "Currit"),
    "条流程": _row("条流程", " chains", " 本のフロー", " cadenas", " catene", " keðjur", " catenae"),
    "已停止": _row("已停止", "Stopped", "停止しました", "Detenido", "Fermato", "Stöðvað", "Sistit"),
    "全局设置运行中": _row("全局设置运行中", "Global settings active", "グローバル設定が実行中", "Ajustes globales activos", "Impostazioni globali attive", "Víðværar stillingar virkar", "Configurationes globales activae"),
    "普通流程完成 · 全局设置持续运行中": _row("普通流程完成 · 全局设置持续运行中", "Normal chains complete · Global settings remain active", "通常フロー完了 · グローバル設定は継続中", "Cadenas normales completadas · Los ajustes globales siguen activos", "Catene normali completate · Le impostazioni globali restano attive", "Venjulegum keðjum lokið · Víðværar stillingar halda áfram", "Catenae ordinariae completae · Configurationes globales permanent"),
    "全局设置未完成配置": _row("全局设置未完成配置", "Global settings are not fully configured", "グローバル設定が未完了です", "Los ajustes globales no están completamente configurados", "Le impostazioni globali non sono completamente configurate", "Víðværar stillingar eru ekki fullstilltar", "Configurationes globales nondum completae"),
    "全局锚点未找到": _row("全局锚点未找到", "Global anchor not found", "グローバルアンカーが見つかりません", "Ancla global no encontrada", "Ancora globale non trovata", "Hnattrænt akkeri fannst ekki", "Ancora globalis non inventa"),
    "多个全局识别范围没有交集": _row("多个全局识别范围没有交集", "Global recognition regions do not overlap", "複数のグローバル認識範囲に共通領域がありません", "Las regiones globales de reconocimiento no se solapan", "Le regioni globali di riconoscimento non si sovrappongono", "Hnattræn greiningarsvæði skarast ekki", "Regiones recognitionis globales non intersecantur"),
    "⚠ 数据类型不匹配：": _row("⚠ 数据类型不匹配：", "⚠ Data type mismatch: ", "⚠ データ型不一致：", "⚠ Tipo de datos incompatible: ", "⚠ Tipo di dati non corrispondente: ", "⚠ Gagnategund passar ekki: ", "⚠ Typus datorum non congruit: "),
    "⚠ 判定提醒：": _row("⚠ 判定提醒：", "⚠ Condition warning: ", "⚠ 条件警告：", "⚠ Aviso de condición: ", "⚠ Avviso condizione: ", "⚠ Skilyrðisviðvörun: ", "⚠ Monitum condicionis: "),
    "锚点：无": _row("锚点：无", "Anchor: None", "アンカー：なし", "Ancla: Ninguna", "Ancora: Nessuna", "Akkeri: Ekkert", "Ancora: Nulla"),
})


# ---------------------------------------------------------------------------
# Remaining workbench dialogs / project management / diagnostics
# ---------------------------------------------------------------------------
_TRANSLATIONS.update({
    "无法读取模板：": _row("无法读取模板：", "Unable to read template: ", "テンプレートを読み込めません：", "No se puede leer la plantilla: ", "Impossibile leggere il modello: ", "Ekki tókst að lesa sniðmát: ", "Exemplar legi non potest: "),
    "ROI 的宽度和高度必须大于 0。": _row("ROI 的宽度和高度必须大于 0。", "ROI width and height must be greater than 0.", "ROI の幅と高さは 0 より大きくする必要があります。", "El ancho y el alto del ROI deben ser mayores que 0.", "Larghezza e altezza ROI devono essere maggiori di 0.", "Breidd og hæð ROI verða að vera stærri en 0.", "Latitudo et altitudo ROI maiores quam 0 esse debent."),
    "正在启动视觉识别系统视角…": _row("正在启动视觉识别系统视角…", "Starting recognition viewport…", "認識ビューを起動中…", "Iniciando vista de reconocimiento…", "Avvio vista riconoscimento…", "Ræsi greiningarsýn…", "Prospectus recognitionis initur…"),
    "视觉识别视角已启动；当前 Windows 环境无法启用截图排除。": _row("视觉识别视角已启动；当前 Windows 环境无法启用截图排除。", "Recognition viewport started; capture exclusion is unavailable in the current Windows environment.", "認識ビューを起動しました。現在の Windows 環境では撮影除外を有効にできません。", "Vista de reconocimiento iniciada; la exclusión de captura no está disponible en este entorno de Windows.", "Vista riconoscimento avviata; l'esclusione dalla cattura non è disponibile nell'ambiente Windows corrente.", "Greiningarsýn ræst; ekki er hægt að útiloka gluggann frá upptöku í þessu Windows-umhverfi.", "Prospectus recognitionis initus est; exclusio captionis in hoc ambitu Windows praesto non est."),
    "Recognition Engine 返回了无效截图结果。": _row("Recognition Engine 返回了无效截图结果。", "Recognition Engine returned an invalid capture result.", "Recognition Engine が無効なキャプチャ結果を返しました。", "Recognition Engine devolvió un resultado de captura no válido.", "Recognition Engine ha restituito un risultato di cattura non valido.", "Recognition Engine skilaði ógildri skjámynd.", "Recognition Engine exitum captionis invalidum reddidit."),
    "视觉识别视角：等待有效截图帧…": _row("视觉识别视角：等待有效截图帧…", "Recognition viewport: waiting for a valid frame…", "認識ビュー：有効なフレームを待機中…", "Vista de reconocimiento: esperando un fotograma válido…", "Vista riconoscimento: attesa di un fotogramma valido…", "Greiningarsýn: bíður eftir gildum ramma…", "Prospectus recognitionis: quadrum validum exspectat…"),
    "感知=": _row("感知=", "Sensing=", "感知=", "Percepción=", "Rilevamento=", "Skynjun=", "Sensus="),
    "感知=未激活": _row("感知=未激活", "Sensing=inactive", "感知=非アクティブ", "Percepción=inactiva", "Rilevamento=inattivo", "Skynjun=óvirk", "Sensus=inactivus"),
    "红框=": _row("红框=", "boxes=", "赤枠=", "cuadros=", "riquadri=", "rammar=", "quadrata="),
    "ROI已回退全屏": _row("ROI已回退全屏", "ROI fell back to fullscreen", "ROI は全画面にフォールバック", "ROI volvió a pantalla completa", "ROI ripiegato su schermo intero", "ROI féll aftur á allan skjá", "ROI ad totum scrinium reductum"),
    "实际视角=": _row("实际视角=", "actual view=", "実際のビュー=", "vista real=", "vista effettiva=", "raunsýn=", "prospectus verus="),
    "视觉识别视角错误：": _row("视觉识别视角错误：", "Recognition viewport error: ", "認識ビューエラー：", "Error de vista de reconocimiento: ", "Errore vista riconoscimento: ", "Villa í greiningarsýn: ", "Error prospectus recognitionis: "),
    "选择锚点模板": _row("选择锚点模板", "Choose anchor template", "アンカーテンプレートを選択", "Elegir plantilla de ancla", "Scegli modello ancora", "Velja akkerissniðmát", "Exemplar ancorae elige"),

    "+0 或 -0": _row("+0 或 -0", "+0 or -0", "+0 または -0", "+0 o -0", "+0 o -0", "+0 eða -0", "+0 vel -0"),
    "必须带 + 或 -，例如 +20、-15": _row("必须带 + 或 -，例如 +20、-15", "Must include + or -, e.g. +20 or -15", "+ または - を付けてください（例：+20、-15）", "Debe incluir + o -, por ejemplo +20 o -15", "Deve includere + o -, ad esempio +20 o -15", "Verður að innihalda + eða -, t.d. +20 eða -15", "Signum + vel - requiritur, ut +20 vel -15"),
    "已选择锚点：X/Y 将作为相对该模板识别坐标的偏移；运行时最终输出仍为全局屏幕坐标。": _row("已选择锚点：X/Y 将作为相对该模板识别坐标的偏移；运行时最终输出仍为全局屏幕坐标。", "Anchor selected: X/Y are offsets from the recognized template coordinate; the final runtime output remains a global screen coordinate.", "アンカー選択済み：X/Y は認識したテンプレート座標からのオフセットです。実行時の最終出力はグローバル画面座標のままです。", "Ancla seleccionada: X/Y son desplazamientos respecto a la coordenada reconocida; la salida final sigue siendo una coordenada global.", "Ancora selezionata: X/Y sono offset rispetto alla coordinata riconosciuta; l'uscita finale resta una coordinata globale.", "Akkeri valið: X/Y eru hliðranir frá greindu sniðmáti; lokaúttak er áfram hnattrænt skjáhnit.", "Ancora selecta: X/Y discessus a coordinata exemplaris agniti sunt; exitus finalis coordinata globalis scrinii manet."),
    "锚点为空：X/Y 直接作为全局虚拟桌面坐标输出。": _row("锚点为空：X/Y 直接作为全局虚拟桌面坐标输出。", "No anchor: X/Y are output directly as global virtual-desktop coordinates.", "アンカーなし：X/Y をそのまま仮想デスクトップのグローバル座標として出力します。", "Sin ancla: X/Y se emiten directamente como coordenadas globales del escritorio virtual.", "Senza ancora: X/Y vengono emessi direttamente come coordinate globali del desktop virtuale.", "Ekkert akkeri: X/Y eru gefin beint út sem hnattræn sýndarskjáborðshnit.", "Sine ancora: X/Y directe ut coordinatae globales desktop virtualis eduntur."),

    "自动缓冲估算：5 ms 模块间隔 +": _row("自动缓冲估算：5 ms 模块间隔 +", "Automatic buffer estimate: 5 ms module gap +", "自動バッファ推定：5 ms のモジュール間隔 +", "Estimación automática de búfer: 5 ms entre módulos +", "Stima buffer automatica: 5 ms tra moduli +", "Sjálfvirkt biðmat: 5 ms milli eininga +", "Aestimatio morae automatica: intervallum 5 ms +"),
    "ms。此缓冲发生在文本发送完成后。": _row("ms。此缓冲发生在文本发送完成后。", "ms. This buffer is applied after text transmission completes.", "ms。このバッファはテキスト送信完了後に適用されます。", "ms. Este búfer se aplica después de completar el envío del texto.", "ms. Questo buffer viene applicato dopo il completamento dell'invio del testo.", "ms. Þessi bið er notuð eftir að textasendingu lýkur.", "ms. Haec mora post textus transmissionem completam adhibetur."),

    "多尺度匹配：以多个缩放比例尝试模板，适合窗口缩放或游戏分辨率导致的目标尺寸变化；会增加识别耗时。": _row("多尺度匹配：以多个缩放比例尝试模板，适合窗口缩放或游戏分辨率导致的目标尺寸变化；会增加识别耗时。", "Multi-scale matching tries the template at several scales. It handles target-size changes caused by window scaling or game resolution, at the cost of additional recognition time.", "マルチスケール照合は複数の倍率でテンプレートを試します。ウィンドウ拡大縮小やゲーム解像度による対象サイズ変化に対応できますが、認識時間が増えます。", "La coincidencia multiescala prueba la plantilla a varias escalas. Ayuda con cambios de tamaño por escalado de ventana o resolución del juego, pero aumenta el tiempo de reconocimiento.", "La corrispondenza multiscala prova il modello a più scale. Gestisce variazioni di dimensione dovute a scala finestra o risoluzione di gioco, aumentando però il tempo di riconoscimento.", "Margkvarðasamsvörun prófar sniðmátið á nokkrum kvörðum. Hún hjálpar við stærðarbreytingar vegna gluggakvörðunar eða upplausnar en tekur lengri tíma.", "Concordantia multiscalaris exemplar pluribus scalis temptat. Mutationes magnitudinis ex scala fenestrae vel resolutione ludi tolerat, sed tempus recognitionis auget."),
    "连续帧确认：要求目标在连续多帧中稳定出现，减少动画、闪烁或偶然误识别；数值越高越稳，但响应更慢。": _row("连续帧确认：要求目标在连续多帧中稳定出现，减少动画、闪烁或偶然误识别；数值越高越稳，但响应更慢。", "Consecutive-frame confirmation requires the target to remain stable across multiple frames, reducing animation/flicker false positives. Higher values are steadier but respond more slowly.", "連続フレーム確認では対象が複数フレームで安定して現れる必要があり、アニメーションやちらつきによる誤認識を減らします。値が高いほど安定しますが応答は遅くなります。", "La confirmación de fotogramas consecutivos exige que el objetivo permanezca estable durante varios fotogramas, reduciendo falsos positivos por animación o parpadeo. Valores mayores son más estables pero más lentos.", "La conferma su fotogrammi consecutivi richiede che il bersaglio resti stabile per più fotogrammi, riducendo falsi positivi da animazioni o sfarfallii. Valori maggiori sono più stabili ma più lenti.", "Staðfesting samfelldra ramma krefst stöðugs marks í mörgum römmum og dregur úr fölskum greiningum vegna hreyfingar eða blikks. Hærra gildi er stöðugra en hægara.", "Confirmatio quadrorum continuorum scopum per plura quadra stabilem requirit, errores ex animatione vel micatu minuens. Valor maior stabilior sed tardior est."),
    "连续帧确认次数：1 表示单帧即可通过；更高数值要求多次识别位置保持接近。": _row("连续帧确认次数：1 表示单帧即可通过；更高数值要求多次识别位置保持接近。", "Consecutive-frame count: 1 accepts a single frame; higher values require repeated detections to stay near the same position.", "連続フレーム回数：1 は1フレームで通過します。高い値では複数回の検出位置が近いことを要求します。", "Número de fotogramas consecutivos: 1 acepta un solo fotograma; valores mayores requieren detecciones repetidas en posiciones próximas.", "Conteggio fotogrammi consecutivi: 1 accetta un singolo fotogramma; valori maggiori richiedono rilevamenti ripetuti in posizioni vicine.", "Fjöldi samfelldra ramma: 1 samþykkir einn ramma; hærri gildi krefjast endurtekinna greininga á svipuðum stað.", "Numerus quadrorum continuorum: 1 unum quadrum accipit; valores maiores detectiones repetitas loco vicino requirunt."),
    "Feature detector：选择 FeatureMatch 用于提取特征点的算法。SIFT 通常更稳健；ORB/BRISK 通常更快；AKAZE/KAZE 介于两者之间。": _row("Feature detector：选择 FeatureMatch 用于提取特征点的算法。SIFT 通常更稳健；ORB/BRISK 通常更快；AKAZE/KAZE 介于两者之间。", "Feature detector: chooses the keypoint algorithm used by FeatureMatch. SIFT is usually more robust; ORB/BRISK are usually faster; AKAZE/KAZE are in between.", "Feature detector：FeatureMatch の特徴点抽出アルゴリズムを選択します。SIFT は通常より堅牢、ORB/BRISK は高速、AKAZE/KAZE は中間です。", "Feature detector: elige el algoritmo de puntos usado por FeatureMatch. SIFT suele ser más robusto; ORB/BRISK más rápidos; AKAZE/KAZE intermedios.", "Feature detector: sceglie l'algoritmo dei punti usato da FeatureMatch. SIFT è generalmente più robusto; ORB/BRISK più veloci; AKAZE/KAZE intermedi.", "Feature detector velur punktareiknirit FeatureMatch. SIFT er yfirleitt traustara; ORB/BRISK hraðari; AKAZE/KAZE þar á milli.", "Feature detector algorithmum punctorum FeatureMatch eligit. SIFT plerumque robustior; ORB/BRISK celeriora; AKAZE/KAZE media."),
    "SIFT：稳健、较慢；AKAZE/KAZE：兼顾精度与速度；BRISK/ORB：速度优先。此选项只影响 FeatureMatch。": _row("SIFT：稳健、较慢；AKAZE/KAZE：兼顾精度与速度；BRISK/ORB：速度优先。此选项只影响 FeatureMatch。", "SIFT: robust but slower; AKAZE/KAZE: balance accuracy and speed; BRISK/ORB: speed first. This setting only affects FeatureMatch.", "SIFT：堅牢だが遅め。AKAZE/KAZE：精度と速度のバランス。BRISK/ORB：速度優先。この設定は FeatureMatch のみに影響します。", "SIFT: robusto pero más lento; AKAZE/KAZE: equilibrio entre precisión y velocidad; BRISK/ORB: prioridad a velocidad. Solo afecta a FeatureMatch.", "SIFT: robusto ma più lento; AKAZE/KAZE: equilibrio precisione/velocità; BRISK/ORB: priorità velocità. Influisce solo su FeatureMatch.", "SIFT: traust en hægara; AKAZE/KAZE: jafnvægi nákvæmni/hraða; BRISK/ORB: hraði fyrst. Hefur aðeins áhrif á FeatureMatch.", "SIFT: robustum sed tardius; AKAZE/KAZE: aequilibrium accuratiae et velocitatis; BRISK/ORB: velocitas prior. Solum FeatureMatch afficit."),
    "“全部”并不是把同一张图重复做六次全屏扫描：UVAF Recognition Engine 会优先 ROI、缓存模板，并复用候选位置；FeatureMatch 用于尺度/旋转变化，灰度与边缘模式用于弱化颜色变化。": _row("“全部”并不是把同一张图重复做六次全屏扫描：UVAF Recognition Engine 会优先 ROI、缓存模板，并复用候选位置；FeatureMatch 用于尺度/旋转变化，灰度与边缘模式用于弱化颜色变化。", "“All” does not repeat six full-screen scans of the same frame. UVAF Recognition Engine prioritizes ROI, caches templates and reuses candidate locations; FeatureMatch handles scale/rotation changes, while grayscale and edge modes reduce sensitivity to color changes.", "「すべて」は同じ画像を6回全画面走査する意味ではありません。UVAF Recognition Engine は ROI を優先し、テンプレートをキャッシュして候補位置を再利用します。FeatureMatch は拡大縮小・回転、グレースケールとエッジは色変化への耐性に使われます。", "«Todos» no realiza seis escaneos completos de la misma imagen. UVAF Recognition Engine prioriza ROI, almacena plantillas y reutiliza posiciones candidatas; FeatureMatch cubre escala/rotación y gris/bordes reduce la sensibilidad al color.", "«Tutti» non esegue sei scansioni complete della stessa immagine. UVAF Recognition Engine privilegia ROI, memorizza i modelli e riusa le posizioni candidate; FeatureMatch gestisce scala/rotazione, mentre grigio e bordi riducono la sensibilità ai colori.", "„Allt“ þýðir ekki sex heildarskjáskannanir á sama ramma. UVAF Recognition Engine forgangsraðar ROI, vistar sniðmát og endurnýtir mögulega staði; FeatureMatch sér um kvarða/snúning og grátónn/jaðar minnka litanæmi.", "«Omnia» non significat sex explorationes totius scrinii eiusdem imaginis. UVAF Recognition Engine ROI praefert, exemplaria servat et loca candidata reutilizat; FeatureMatch scalam/rotationem tractat, cinereum/margines mutationes coloris minuunt."),

    "复制失败": _row("复制失败", "Copy failed", "コピー失敗", "Error al copiar", "Copia non riuscita", "Afritun mistókst", "Copia defecit"),
    "名称无效": _row("名称无效", "Invalid name", "無効な名前", "Nombre no válido", "Nome non valido", "Ógilt nafn", "Nomen invalidum"),
    "请输入有效的模板名称。": _row("请输入有效的模板名称。", "Enter a valid template name.", "有効なテンプレート名を入力してください。", "Introduce un nombre de plantilla válido.", "Inserisci un nome modello valido.", "Sláðu inn gilt sniðmátsheiti.", "Nomen exemplaris validum insere."),
    "覆盖锚点模板": _row("覆盖锚点模板", "Overwrite anchor template", "アンカーテンプレートを上書き", "Sobrescribir plantilla de ancla", "Sovrascrivi modello ancora", "Yfirskrifa akkerissniðmát", "Exemplar ancorae superscribe"),
    "无法写入 PNG 文件。": _row("无法写入 PNG 文件。", "Unable to write PNG file.", "PNG ファイルを書き込めません。", "No se puede escribir el archivo PNG.", "Impossibile scrivere il file PNG.", "Ekki tókst að skrifa PNG-skrá.", "Fasciculus PNG scribi non potest."),
    "保存锚点模板失败": _row("保存锚点模板失败", "Failed to save anchor template", "アンカーテンプレートの保存に失敗", "Error al guardar la plantilla de ancla", "Salvataggio modello ancora non riuscito", "Vista akkerissniðmát mistókst", "Servatio exemplaris ancorae defecit"),
    "锚点模板已创建": _row("锚点模板已创建", "Anchor template created", "アンカーテンプレートを作成しました", "Plantilla de ancla creada", "Modello ancora creato", "Akkerissniðmát búið til", "Exemplar ancorae creatum"),
    "已保存到当前项目模板库：": _row("已保存到当前项目模板库：", "Saved to current project template library: ", "現在のプロジェクトのテンプレートライブラリに保存：", "Guardado en la biblioteca de plantillas del proyecto: ", "Salvato nella libreria modelli del progetto: ", "Vistað í sniðmátasafn verkefnis: ", "Servatum in bibliotheca exemplarium projecti: "),
    "截取区域：": _row("截取区域：", "Captured region: ", "キャプチャ領域：", "Región capturada: ", "Regione catturata: ", "Tekið svæði: ", "Regio capta: "),

    "占位1": _row("占位1", "Placeholder 1", "プレースホルダー1", "Marcador 1", "Segnaposto 1", "Staðgengill 1", "Locus 1"),
    "占位2": _row("占位2", "Placeholder 2", "プレースホルダー2", "Marcador 2", "Segnaposto 2", "Staðgengill 2", "Locus 2"),
    "占位": _row("占位", "Placeholder", "プレースホルダー", "Marcador", "Segnaposto", "Staðgengill", "Locus"),
    "必须带正负号，例如 +20 或 -15": _row("必须带正负号，例如 +20 或 -15", "Must include a sign, e.g. +20 or -15", "符号が必要です（例：+20、-15）", "Debe incluir signo, p. ej. +20 o -15", "Deve includere un segno, es. +20 o -15", "Verður að hafa formerki, t.d. +20 eða -15", "Signum requiritur, ut +20 vel -15"),
    "当前无法访问 Recognition Engine。": _row("当前无法访问 Recognition Engine。", "Recognition Engine is currently unavailable.", "現在 Recognition Engine にアクセスできません。", "Recognition Engine no está disponible actualmente.", "Recognition Engine non è attualmente disponibile.", "Recognition Engine er ekki tiltækt núna.", "Recognition Engine nunc praesto non est."),
    "识别引擎不可用": _row("识别引擎不可用", "Recognition engine unavailable", "認識エンジン利用不可", "Motor de reconocimiento no disponible", "Motore di riconoscimento non disponibile", "Greiningarvél ekki tiltæk", "Machina recognitionis non praesto"),
    "选择模板  ▼": _row("选择模板  ▼", "Choose template  ▼", "テンプレートを選択  ▼", "Elegir plantilla  ▼", "Scegli modello  ▼", "Velja sniðmát  ▼", "Exemplar elige  ▼"),
    "持续扫描直到发现（坐标输出）": _row("持续扫描直到发现（坐标输出）", "Scan until found (coordinate output)", "発見まで走査（座標出力）", "Escanear hasta encontrar (salida de coordenadas)", "Scansiona fino a trovare (uscita coordinate)", "Skanna þar til finnst (hnit úttak)", "Explora donec inveniatur (coordinatae)"),
    "未选择锚点": _row("未选择锚点", "No anchor selected", "アンカー未選択", "Sin ancla seleccionada", "Nessuna ancora selezionata", "Ekkert akkeri valið", "Nulla ancora selecta"),
    "快捷创建模板": _row("快捷创建模板", "Quick template capture", "クイックテンプレート作成", "Captura rápida de plantilla", "Acquisizione rapida modello", "Flýtisniðmát", "Exemplar celeriter"),

    "创建失败": _row("创建失败", "Creation failed", "作成に失敗", "Error al crear", "Creazione non riuscita", "Sköpun mistókst", "Creatio defecit"),
    "导入 UVAF 项目": _row("导入 UVAF 项目", "Import UVAF project", "UVAF プロジェクトをインポート", "Importar proyecto UVAF", "Importa progetto UVAF", "Flytja inn UVAF-verkefni", "Projectum UVAF importa"),
    "导入失败": _row("导入失败", "Import failed", "インポート失敗", "Error al importar", "Importazione non riuscita", "Innflutningur mistókst", "Importatio defecit"),
    "时钟终止后链": _row("时钟终止后链", "Clock end chain", "時計終了後チェーン", "Cadena al terminar el reloj", "Catena dopo fine timer", "Keðja eftir klukkulok", "Catena post horologium"),
    "自定义模块文件格式无效。": _row("自定义模块文件格式无效。", "Invalid custom-module file format.", "カスタムモジュールファイル形式が無効です。", "Formato de archivo de módulo personalizado no válido.", "Formato file modulo personalizzato non valido.", "Ógilt skráarsnið sérsniðinnar einingar.", "Forma fasciculi moduli consuetudinalis invalida."),
    "这不是 UVAF 自定义模块文件。": _row("这不是 UVAF 自定义模块文件。", "This is not a UVAF custom-module file.", "これは UVAF カスタムモジュールファイルではありません。", "Este no es un archivo de módulo personalizado de UVAF.", "Questo non è un file modulo personalizzato UVAF.", "Þetta er ekki UVAF-sérsniðin einingaskrá.", "Hic fasciculus moduli consuetudinalis UVAF non est."),
    "自定义模块缺少工作流数据。": _row("自定义模块缺少工作流数据。", "Custom module is missing workflow data.", "カスタムモジュールにワークフローデータがありません。", "Al módulo personalizado le faltan datos del flujo.", "Il modulo personalizzato non contiene dati del flusso.", "Sérsniðna eininguna vantar flæðisgögn.", "Modulo consuetudinali data fluxus desunt."),
    "无法打开文件位置": _row("无法打开文件位置", "Unable to open file location", "ファイルの場所を開けません", "No se puede abrir la ubicación del archivo", "Impossibile aprire il percorso del file", "Ekki tókst að opna skráarstað", "Locus fasciculi aperiri non potest"),
    "删除自定义模块": _row("删除自定义模块", "Delete custom module", "カスタムモジュールを削除", "Eliminar módulo personalizado", "Elimina modulo personalizzato", "Eyða sérsniðinni einingu", "Modulum consuetudinalem dele"),
    "删除失败": _row("删除失败", "Delete failed", "削除失敗", "Error al eliminar", "Eliminazione non riuscita", "Eyðing mistókst", "Deletio defecit"),
    "没有选择模块": _row("没有选择模块", "No modules selected", "モジュールが選択されていません", "No hay módulos seleccionados", "Nessun modulo selezionato", "Engar einingar valdar", "Nulli moduli selecti"),
    "请先用左键框选或选择要保存的模块。": _row("请先用左键框选或选择要保存的模块。", "Use left-drag selection or select the modules you want to save first.", "まず左ドラッグで範囲選択するか、保存するモジュールを選択してください。", "Primero selecciona con arrastre izquierdo o elige los módulos que quieras guardar.", "Prima seleziona con trascinamento sinistro o scegli i moduli da salvare.", "Veldu fyrst einingarnar með vinstri ramma eða annarri valaðferð.", "Primum modulos servandos sinistro tractu vel selectione elige."),
    "请输入有效名称。": _row("请输入有效名称。", "Enter a valid name.", "有効な名前を入力してください。", "Introduce un nombre válido.", "Inserisci un nome valido.", "Sláðu inn gilt nafn.", "Nomen validum insere."),
    "覆盖自定义模块": _row("覆盖自定义模块", "Overwrite custom module", "カスタムモジュールを上書き", "Sobrescribir módulo personalizado", "Sovrascrivi modulo personalizzato", "Yfirskrifa sérsniðna einingu", "Modulum consuetudinalem superscribe"),
    "无法载入自定义模块": _row("无法载入自定义模块", "Unable to load custom module", "カスタムモジュールを読み込めません", "No se puede cargar el módulo personalizado", "Impossibile caricare il modulo personalizzato", "Ekki tókst að hlaða sérsniðinni einingu", "Modulus consuetudinalis onerari non potest"),
    "模式不匹配": _row("模式不匹配", "Mode mismatch", "モード不一致", "Modo incompatible", "Modalità non corrispondente", "Hamur passar ekki", "Modus non congruit"),
    "复杂模式": _row("复杂模式", "Complex mode", "複雑モード", "Modo complejo", "Modalità complessa", "Flókinn hamur", "Modus complexus"),
    "拼图模式": _row("拼图模式", "Puzzle mode", "パズルモード", "Modo puzle", "Modalità puzzle", "Púslhamur", "Modus tessellarum"),
    "放置自定义模块失败": _row("放置自定义模块失败", "Failed to place custom module", "カスタムモジュールの配置に失敗", "Error al colocar el módulo personalizado", "Posizionamento modulo personalizzato non riuscito", "Ekki tókst að setja niður sérsniðna einingu", "Positio moduli consuetudinalis defecit"),
    "无法打开项目文件夹": _row("无法打开项目文件夹", "Unable to open project folder", "プロジェクトフォルダーを開けません", "No se puede abrir la carpeta del proyecto", "Impossibile aprire la cartella progetto", "Ekki tókst að opna verkefnismöppu", "Directorium projecti aperiri non potest"),
    "导出 UVAF 项目": _row("导出 UVAF 项目", "Export UVAF project", "UVAF プロジェクトをエクスポート", "Exportar proyecto UVAF", "Esporta progetto UVAF", "Flytja út UVAF-verkefni", "Projectum UVAF exporta"),
    "导出失败": _row("导出失败", "Export failed", "エクスポート失敗", "Error al exportar", "Esportazione non riuscita", "Útflutningur mistókst", "Exportatio defecit"),
    "未选择项目": _row("未选择项目", "No project selected", "プロジェクト未選択", "No hay proyecto seleccionado", "Nessun progetto selezionato", "Ekkert verkefni valið", "Nullum projectum selectum"),
    "请先在项目库中选择要删除的项目。": _row("请先在项目库中选择要删除的项目。", "Select the project to delete from the project library first.", "まずプロジェクトライブラリで削除するプロジェクトを選択してください。", "Selecciona primero en la biblioteca el proyecto que quieras eliminar.", "Seleziona prima nella libreria il progetto da eliminare.", "Veldu fyrst verkefnið sem á að eyða úr verkefnasafninu.", "Primum projectum delendum in bibliotheca projectorum elige."),
    "确认永久删除": _row("确认永久删除", "Confirm permanent deletion", "完全削除を確認", "Confirmar eliminación permanente", "Conferma eliminazione permanente", "Staðfesta varanlega eyðingu", "Deletionem permanentem confirma"),
    "名称不匹配": _row("名称不匹配", "Name does not match", "名前が一致しません", "El nombre no coincide", "Il nome non corrisponde", "Nafn passar ekki", "Nomen non congruit"),
    "项目名称不匹配，未执行删除。": _row("项目名称不匹配，未执行删除。", "Project name does not match; nothing was deleted.", "プロジェクト名が一致しないため削除しませんでした。", "El nombre del proyecto no coincide; no se eliminó nada.", "Il nome del progetto non corrisponde; nessuna eliminazione eseguita.", "Verkefnisheiti passar ekki; engu var eytt.", "Nomen projecti non congruit; nihil deletum est."),
    "保存失败": _row("保存失败", "Save failed", "保存失敗", "Error al guardar", "Salvataggio non riuscito", "Vistun mistókst", "Servatio defecit"),
    "覆盖模板": _row("覆盖模板", "Overwrite template", "テンプレートを上書き", "Sobrescribir plantilla", "Sovrascrivi modello", "Yfirskrifa sniðmát", "Exemplar superscribe"),
    "已存在，是否覆盖？": _row("已存在，是否覆盖？", "already exists. Overwrite it?", "はすでに存在します。上書きしますか？", "ya existe. ¿Sobrescribir?", "esiste già. Sovrascriverlo?", "er þegar til. Yfirskrifa?", "iam exstat. Superscribere?"),
})


# ---------------------------------------------------------------------------
# Dynamic fragments: utilities, workbench warnings and runtime logs
# ---------------------------------------------------------------------------
_TRANSLATIONS.update({
    "正在等待识别。": _row("正在等待识别。", "Waiting for recognition.", "認識待機中。", "Esperando reconocimiento.", "In attesa del riconoscimento.", "Bíður eftir greiningu.", "Recognitionem exspectat."),
    "Windows 坐标读取失败：": _row("Windows 坐标读取失败：", "Failed to read Windows coordinates: ", "Windows 座標の取得に失敗：", "Error al leer las coordenadas de Windows: ", "Lettura coordinate Windows non riuscita: ", "Mistókst að lesa Windows-hnit: ", "Lectio coordinatarum Windows defecit: "),
    "警告：鼠标坐标超出 Windows 返回的虚拟桌面范围": _row("警告：鼠标坐标超出 Windows 返回的虚拟桌面范围", "Warning: mouse coordinates are outside the virtual desktop reported by Windows", "警告：マウス座標が Windows の仮想デスクトップ範囲外です", "Aviso: las coordenadas del ratón están fuera del escritorio virtual indicado por Windows", "Avviso: le coordinate del mouse sono fuori dal desktop virtuale restituito da Windows", "Viðvörun: músarhnit eru utan sýndarskjáborðs Windows", "Monitum: coordinatae muris extra desktop virtuale a Windows relatum sunt"),
    "每 0.2 秒刷新 · 按 K 记录": _row("每 0.2 秒刷新 · 按 K 记录", "Refreshes every 0.2 s · Press K to record", "0.2 秒ごとに更新 · K で記録", "Actualiza cada 0,2 s · Pulsa K para registrar", "Aggiorna ogni 0,2 s · Premi K per registrare", "Uppfærir á 0,2 sek. fresti · Ýttu K til að skrá", "Singulis 0.2 s renovatur · Preme K ut registres"),
    "坐标系：Windows 物理全局坐标 ·": _row("坐标系：Windows 物理全局坐标 ·", "Coordinate system: Windows physical global coordinates ·", "座標系：Windows 物理グローバル座標 ·", "Sistema de coordenadas: coordenadas físicas globales de Windows ·", "Sistema di coordinate: coordinate fisiche globali Windows ·", "Hnitakerfi: hnattræn Windows-raunhnit ·", "Systema coordinatarum: coordinatae physicae globales Windows ·"),
    "当前不可记录相对坐标": _row("当前不可记录相对坐标", "relative coordinates cannot be recorded yet", "現在は相対座標を記録できません", "aún no se pueden registrar coordenadas relativas", "le coordinate relative non possono ancora essere registrate", "ekki er enn hægt að skrá afstæð hnit", "coordinatae relativae nondum registrari possunt"),
    "鼠标与锚点均使用 Windows 物理坐标": _row("鼠标与锚点均使用 Windows 物理坐标", "mouse and anchor both use Windows physical coordinates", "マウスとアンカーはいずれも Windows 物理座標を使用", "el ratón y el ancla usan coordenadas físicas de Windows", "mouse e ancora usano coordinate fisiche Windows", "mús og akkeri nota bæði Windows-raunhnit", "mus et ancora ambo coordinatis physicis Windows utuntur"),
    "按 K 可继续记录": _row("按 K 可继续记录", "Press K to keep recording", "K で続けて記録", "Pulsa K para seguir registrando", "Premi K per continuare a registrare", "Ýttu K til að halda áfram að skrá", "Preme K ut pergat registratio"),
    "红框=": _row("红框=", "boxes=", "赤枠=", "cuadros=", "riquadri=", "rammar=", "quadrata="),
    "ROI已回退全屏": _row("ROI已回退全屏", "ROI fell back to fullscreen", "ROI は全画面にフォールバック", "ROI volvió a pantalla completa", "ROI ripiegato su schermo intero", "ROI féll aftur á allan skjá", "ROI ad totum scrinium reductum"),

    "例如 758,373": _row("例如 758,373", "e.g. 758,373", "例：758,373", "p. ej. 758,373", "es. 758,373", "t.d. 758,373", "e.g. 758,373"),
    "例如 1920*800": _row("例如 1920*800", "e.g. 1920*800", "例：1920*800", "p. ej. 1920*800", "es. 1920*800", "t.d. 1920*800", "e.g. 1920*800"),
    "坐标示例：758,373；大小示例：1920*800。": _row("坐标示例：758,373；大小示例：1920*800。", "Coordinate example: 758,373; size example: 1920*800.", "座標例：758,373、サイズ例：1920*800。", "Ejemplo de coordenada: 758,373; ejemplo de tamaño: 1920*800.", "Esempio coordinate: 758,373; esempio dimensione: 1920*800.", "Dæmi um hnit: 758,373; stærð: 1920*800.", "Exemplum coordinatae: 758,373; magnitudinis: 1920*800."),
    "该动作会在判定时执行，但不直接提供判定值。": _row("该动作会在判定时执行，但不直接提供判定值。", "This action executes during evaluation but does not directly provide a condition value.", "このアクションは判定時に実行されますが、判定値そのものは提供しません。", "Esta acción se ejecuta durante la evaluación, pero no aporta directamente un valor de condición.", "Questa azione viene eseguita durante la valutazione ma non fornisce direttamente un valore di condizione.", "Þessi aðgerð keyrir við mat en gefur ekki beint skilyrðisgildi.", "Haec actio tempore iudicii exsequitur sed valorem condicionis directe non dat."),
    "判定分支包含动作模块": _row("判定分支包含动作模块", "condition branch contains action modules", "条件分岐にアクションモジュールがあります", "la rama de condición contiene módulos de acción", "il ramo condizione contiene moduli azione", "skilyrðisgrein inniheldur aðgerðaeiningar", "ramus condicionis modulos actionis continet"),
    "的判定分支包含动作模块。": _row("的判定分支包含动作模块。", " condition branch contains action modules.", " の条件分岐にアクションモジュールがあります。", " contiene módulos de acción en la rama de condición.", " contiene moduli azione nel ramo condizione.", " hefur aðgerðaeiningar í skilyrðisgrein.", " ramus condicionis modulos actionis continet."),
    "的判定框包含动作模块；动作会执行，但不直接提供判定值。": _row("的判定框包含动作模块；动作会执行，但不直接提供判定值。", " condition contains action modules; they execute but do not directly provide a condition value.", " の条件枠にアクションモジュールがあります。実行されますが判定値を直接提供しません。", " contiene módulos de acción en la condición; se ejecutan pero no aportan directamente un valor.", " contiene moduli azione nella condizione; vengono eseguiti ma non forniscono direttamente un valore.", " inniheldur aðgerðaeiningar í skilyrði; þær keyra en gefa ekki beint gildi.", " condicio modulos actionis continet; exsequuntur sed valorem iudicii directe non dant."),
    "输出": _row("输出", "output", "出力", "salida", "uscita", "úttak", "exitus"),
    "需要": _row("需要", "requires", "必要", "requiere", "richiede", "krefst", "requirit"),
    "（另有": _row("（另有", " (plus ", "（ほかに", " (más ", " (oltre ", " (auk ", " (praeterea "),
    "处）": _row("处）", " more)", " 件）", " más)", " altri)", " tilvik)", " alia)"),

    "确定删除“": _row("确定删除“", "Delete “", "「", "¿Eliminar «", "Eliminare «", "Eyða „", "Dele «"),
    "”吗？": _row("”吗？", "”?", "」を削除しますか？", "»?", "»?", "“?", "»?"),
    "”已经存在。是否覆盖？": _row("”已经存在。是否覆盖？", "” already exists. Overwrite it?", "」はすでに存在します。上書きしますか？", "» ya existe. ¿Sobrescribir?", "» esiste già. Sovrascrivere?", "“ er þegar til. Yfirskrifa?", "» iam exstat. Superscribere?"),
    "这个自定义模块创建于": _row("这个自定义模块创建于", "This custom module was created in ", "このカスタムモジュールは ", "Este módulo personalizado se creó en ", "Questo modulo personalizzato è stato creato in ", "Þessi sérsniðna eining var búin til í ", "Hic modulus consuetudinalis creatus est in "),
    "。请切换到对应模式后再拖入。": _row("。请切换到对应模式后再拖入。", ". Switch to the matching mode before dragging it in.", "。対応するモードに切り替えてからドラッグしてください。", ". Cambia al modo correspondiente antes de arrastrarlo.", ". Passa alla modalità corrispondente prima di trascinarlo.", ". Skiptu í samsvarandi ham áður en þú dregur hana inn.", ". Ad modum congruentem muta antequam trahas."),
    "确定永久删除项目“": _row("确定永久删除项目“", "Permanently delete project “", "プロジェクト「", "¿Eliminar permanentemente el proyecto «", "Eliminare definitivamente il progetto «", "Eyða verkefninu „", "Projectum «"),
    "”确认：": _row("”确认：", "” to confirm: ", "」を確認：", "» para confirmar: ", "» per confermare: ", "“ til staðfestingar: ", "» ad confirmandum: "),

    # Runtime logs
    "时钟已启动：": _row("时钟已启动：", "Clock started: ", "タイマー開始：", "Reloj iniciado: ", "Timer avviato: ", "Klukka ræst: ", "Horologium initum: "),
    "时钟结束：": _row("时钟结束：", "Clock ended: ", "タイマー終了：", "Reloj finalizado: ", "Timer terminato: ", "Klukku lokið: ", "Horologium finitum: "),
    "时钟：已终止其他事件链条，开始执行时钟终止后链。": _row("时钟：已终止其他事件链条，开始执行时钟终止后链。", "Clock: other event chains stopped; executing the clock-end chain.", "タイマー：他のイベントチェーンを停止し、時計終了後チェーンを実行します。", "Reloj: se detuvieron otras cadenas; se ejecuta la cadena de finalización.", "Timer: fermate le altre catene; esecuzione della catena di fine timer.", "Klukka: aðrar atburðakeðjur stöðvaðar; keyrir lokakeðju.", "Horologium: aliae catenae eventuum sistuntur; catena finis exsequitur."),
    "全局设置已持续启用：": _row("全局设置已持续启用：", "Global settings remain enabled: ", "グローバル設定を継続して有効化：", "Ajustes globales activos continuamente: ", "Impostazioni globali mantenute attive: ", "Víðværar stillingar áfram virkar: ", "Configurationes globales continue activae: "),
    "没有可执行内容。": _row("没有可执行内容。", "No executable content.", "実行可能な内容がありません。", "No hay contenido ejecutable.", "Nessun contenuto eseguibile.", "Ekkert keyranlegt efni.", "Nullum contentum exsequendum."),
    "流程": _row("流程", "Chain", "フロー", "Cadena", "Catena", "Keðja", "Catena"),
    "：自定义模块": _row("：自定义模块", ": custom module ", "：カスタムモジュール ", ": módulo personalizado ", ": modulo personalizzato ", ": sérsniðin eining ", ": modulus consuetudinalis "),
    "完成": _row("完成", "complete", "完了", "completado", "completato", "lokið", "completum"),
    "：循环完成 ·": _row("：循环完成 ·", ": loop complete ·", "：ループ完了 ·", ": bucle completado ·", ": ciclo completato ·", ": lykkju lokið ·", ": iteratio completa ·"),
    "：循环…直到…终止分支已完成": _row("：循环…直到…终止分支已完成", ": Loop…until… termination branch completed", "：ループ…まで…の終了分岐が完了", ": rama de terminación de Bucle…hasta… completada", ": ramo di terminazione Ciclo…finché… completato", ": lokagrein Lykkja…þar til… lokið", ": ramus terminalis Itera…donec… completus"),
    "：IF 判定 →": _row("：IF 判定 →", ": IF condition →", "：IF 判定 →", ": condición IF →", ": condizione IF →", ": IF-skilyrði →", ": condicio IF →"),
    "结果=": _row("结果=", "result=", "結果=", "resultado=", "risultato=", "niðurstaða=", "exitus="),
    "：仅识别锚点未完成设置。": _row("：仅识别锚点未完成设置。", ": Anchor-only recognition is not fully configured.", "：アンカー限定認識の設定が未完了です。", ": el reconocimiento limitado al ancla no está configurado por completo.", ": riconoscimento limitato all'ancora non configurato completamente.", ": greining við akkeri er ekki fullstillt.", ": recognitio ad ancoram nondum completa est."),
    "：全局锚点未找到。": _row("：全局锚点未找到。", ": global anchor not found.", "：グローバルアンカーが見つかりません。", ": ancla global no encontrada.", ": ancora globale non trovata.", ": hnattrænt akkeri fannst ekki.", ": ancora globalis non inventa."),
    "：全局识别视野已限制为": _row("：全局识别视野已限制为", ": global recognition view restricted to ", "：グローバル認識視野を制限：", ": vista global de reconocimiento limitada a ", ": vista globale di riconoscimento limitata a ", ": hnattrænt greiningarsvið takmarkað við ", ": prospectus recognitionis globalis restrictus ad "),
    "：ROI 与全局识别视野没有交集。": _row("：ROI 与全局识别视野没有交集。", ": ROI does not overlap the global recognition view.", "：ROI とグローバル認識視野が重なりません。", ": ROI no se solapa con la vista global de reconocimiento.", ": ROI non si sovrappone alla vista globale di riconoscimento.", ": ROI skarast ekki við hnattrænt greiningarsvið.", ": ROI cum prospectu recognitionis globali non intersecatur."),
    "：坐标修改需要一个坐标输入，实际输入=": _row("：坐标修改需要一个坐标输入，实际输入=", ": Modify Coordinate requires coordinate input; received=", "：座標変更には座標入力が必要です。実際の入力=", ": Modificar coordenada requiere una coordenada; recibido=", ": Modifica coordinata richiede una coordinata; ricevuto=", ": Hnitabreyting krefst hnits; fékk=", ": Mutatio coordinatae ingressum coordinatae requirit; acceptum="),
    "：坐标修改收到的坐标无法转换为数值。": _row("：坐标修改收到的坐标无法转换为数值。", ": coordinate input could not be converted to numbers.", "：座標入力を数値に変換できません。", ": la coordenada recibida no se pudo convertir a números.", ": la coordinata ricevuta non può essere convertita in numeri.", ": ekki tókst að breyta hnitinu í tölur.", ": coordinata accepta in numeros converti non potest."),
    "：坐标修改": _row("：坐标修改", ": modify coordinate ", "：座標変更 ", ": modificar coordenada ", ": modifica coordinata ", ": breyta hniti ", ": coordinatam muta "),
    "：固定坐标的锚点搜索范围为空。": _row("：固定坐标的锚点搜索范围为空。", ": Fixed Coordinate anchor search region is empty.", "：固定座標のアンカー検索範囲が空です。", ": la región de búsqueda del ancla de Coordenada fija está vacía.", ": la regione di ricerca ancora di Coordinata fissa è vuota.", ": leitarsvæði akkeris fyrir Fast hnit er tómt.", ": regio quaestionis ancorae coordinatae fixae vacua est."),
    "：固定坐标锚点识别失败：": _row("：固定坐标锚点识别失败：", ": Fixed Coordinate anchor recognition failed: ", "：固定座標アンカー認識失敗：", ": falló el reconocimiento del ancla de Coordenada fija: ", ": riconoscimento ancora Coordinata fissa non riuscito: ", ": greining akkeris fyrir Fast hnit mistókst: ", ": recognitio ancorae coordinatae fixae defecit: "),
    "：固定坐标未找到锚点。": _row("：固定坐标未找到锚点。", ": Fixed Coordinate did not find its anchor.", "：固定座標のアンカーが見つかりません。", ": Coordenada fija no encontró su ancla.", ": Coordinata fissa non ha trovato l'ancora.", ": Fast hnit fann ekki akkeri.", ": Coordinata fixa ancoram non invenit."),
    "锚点=": _row("锚点=", "anchor=", "アンカー=", "ancla=", "ancora=", "akkeri=", "ancora="),
    "：固定坐标 →": _row("：固定坐标 →", ": fixed coordinate →", "：固定座標 →", ": coordenada fija →", ": coordinata fissa →", ": fast hnit →", ": coordinata fixa →"),

    "扫描模板": _row("扫描模板", "Scan template", "テンプレート走査", "Escanear plantilla", "Scansiona modello", "Skanna sniðmát", "Exemplar explora"),
    "模板计数": _row("模板计数", "Template count", "テンプレート数", "Conteo de plantilla", "Conteggio modello", "Sniðmátatalning", "Numeratio exemplarium"),
    "锁定模板": _row("锁定模板", "Lock template", "テンプレート追跡", "Bloquear plantilla", "Blocca modello", "Læsa sniðmáti", "Exemplar fige"),
    "：模板计数 →": _row("：模板计数 →", ": template count →", "：テンプレート数 →", ": conteo de plantilla →", ": conteggio modello →", ": sniðmátatalning →", ": numeratio exemplarium →"),
    "：锁定模板已消失": _row("：锁定模板已消失", ": locked template disappeared", "：追跡テンプレートが消失", ": la plantilla bloqueada desapareció", ": il modello bloccato è scomparso", ": læst sniðmát hvarf", ": exemplar fixum evanuit"),
    "：锁定模板 → (": _row("：锁定模板 → (", ": locked template → (", "：追跡テンプレート → (", ": plantilla bloqueada → (", ": modello bloccato → (", ": læst sniðmát → (", ": exemplar fixum → ("),
    "：扫描模板未命中": _row("：扫描模板未命中", ": Scan Template found no match", "：テンプレート走査で一致なし", ": Escanear plantilla no encontró coincidencia", ": Scansiona modello senza corrispondenza", ": sniðmátaskönnun fann ekkert", ": exploratio exemplaris nihil invenit"),
    "：扫描模板等待识别超时 ·": _row("：扫描模板等待识别超时 ·", ": Scan Template wait timed out ·", "：テンプレート走査の待機タイムアウト ·", ": espera de Escanear plantilla agotada ·", ": attesa Scansiona modello scaduta ·", ": bið sniðmátaskönnunar rann út ·", ": mora explorationis exemplaris expleta ·"),
    "尝试": _row("尝试", "attempts", "試行", "intentos", "tentativi", "tilraunir", "conatus"),
    "靠近锚点": _row("靠近锚点", "nearest anchor", "アンカーに最も近い", "más cercano al ancla", "più vicino all'ancora", "næst akkeri", "ancorae proximum"),
    "最左侧": _row("最左侧", "leftmost", "最左", "más a la izquierda", "più a sinistra", "lengst til vinstri", "sinistrissimum"),
    "候选": _row("候选", "candidates", "候補", "candidatos", "candidati", "möguleikar", "candidata"),
    "选择": _row("选择", "selection", "選択", "selección", "selezione", "val", "selectio"),

    "：移至需要上一个模块提供坐标数据。": _row("：移至需要上一个模块提供坐标数据。", ": Move To requires coordinate data from the previous module.", "：移動には前のモジュールからの座標データが必要です。", ": Mover a necesita coordenadas del módulo anterior.", ": Sposta a richiede coordinate dal modulo precedente.", ": Færa til krefst hnita frá fyrri einingu.", ": Move ad coordinatas a modulo priore requirit."),
    "：移至缺少坐标输入": _row("：移至缺少坐标输入", ": Move To is missing coordinate input", "：移動に座標入力がありません", ": Mover a no tiene coordenada de entrada", ": Sposta a non ha coordinate in ingresso", ": Færa til vantar hnit", ": Move ad coordinata ingressa deest"),
    "：移至拒绝非全局屏幕坐标输入。": _row("：移至拒绝非全局屏幕坐标输入。", ": Move To rejects non-global screen coordinates.", "：移動はグローバル画面座標以外を受け付けません。", ": Mover a rechaza coordenadas que no sean globales de pantalla.", ": Sposta a rifiuta coordinate non globali dello schermo.", ": Færa til hafnar hnitum sem eru ekki hnattræn skjáhnit.", ": Move ad coordinatas non-globales scrinii recusat."),
    "：移至收到的不是全局屏幕坐标": _row("：移至收到的不是全局屏幕坐标", ": Move To received non-global screen coordinates", "：移動がグローバル画面座標以外を受信", ": Mover a recibió coordenadas no globales", ": Sposta a ha ricevuto coordinate non globali", ": Færa til fékk ekki hnattræn skjáhnit", ": Move ad coordinatas non-globales accepit"),
    "：移至 → (": _row("：移至 → (", ": move to → (", "：移動 → (", ": mover a → (", ": sposta a → (", ": færa til → (", ": move ad → ("),
    "随机路线": _row("随机路线", "random path", "ランダム経路", "ruta aleatoria", "percorso casuale", "handahófsleið", "iter fortuitum"),
    "移至失败：": _row("移至失败：", "Move To failed: ", "移動失敗：", "Mover a falló: ", "Sposta a non riuscito: ", "Færa til mistókst: ", "Move ad defecit: "),
    "：移至失败": _row("：移至失败", ": Move To failed", "：移動失敗", ": Mover a falló", ": Sposta a non riuscito", ": Færa til mistókst", ": Move ad defecit"),
    "：点击 ×": _row("：点击 ×", ": click ×", "：クリック ×", ": clic ×", ": clic ×", ": smellur ×", ": preme ×"),
    "点击失败：": _row("点击失败：", "Click failed: ", "クリック失敗：", "Clic falló: ", "Clic non riuscito: ", "Smellur mistókst: ", "Pressio defecit: "),
    "：点击失败": _row("：点击失败", ": click failed", "：クリック失敗", ": clic falló", ": clic non riuscito", ": smellur mistókst", ": pressio defecit"),
    "：拖动 →": _row("：拖动 →", ": drag →", "：ドラッグ →", ": arrastrar →", ": trascina →", ": draga →", ": trahe →"),
    "：文本输入": _row("：文本输入", ": text input ", "：テキスト入力 ", ": entrada de texto ", ": input testo ", ": textainntak ", ": ingressus textus "),
    "字符 · 自动处理缓冲": _row("字符 · 自动处理缓冲", " characters · automatic processing buffer ", " 文字 · 自動処理バッファ ", " caracteres · búfer automático ", " caratteri · buffer automatico ", " stafir · sjálfvirk bið ", " litterae · mora automatica "),
    "ms (+ 下一模块固定 5 ms)": _row("ms (+ 下一模块固定 5 ms)", "ms (+ fixed 5 ms before next module)", "ms（+ 次モジュール前の固定 5 ms）", "ms (+ 5 ms fijos antes del siguiente módulo)", "ms (+ 5 ms fissi prima del modulo successivo)", "ms (+ föst 5 ms fyrir næstu einingu)", "ms (+ 5 ms fixa ante modulum sequentem)"),
    "：键盘": _row("：键盘", ": keyboard ", "：キーボード ", ": teclado ", ": tastiera ", ": lyklaborð ", ": claviatura "),
    "：已启动": _row("：已启动", ": launched", "：起動済み", ": iniciado", ": avviato", ": ræst", ": initum"),
    "启动程序失败：": _row("启动程序失败：", "Launch program failed: ", "プログラム起動失敗：", "Error al iniciar programa: ", "Avvio programma non riuscito: ", "Forritsræsing mistókst: ", "Initiatio programmatis defecit: "),
    "：延时等待": _row("：延时等待", ": delay ", "：待機 ", ": espera ", ": attesa ", ": bið ", ": mora "),
    "未标记": _row("未标记", "unmarked", "未マーク", "sin marcar", "non contrassegnato", "ómerkt", "non signatum"),
    "无交集": _row("无交集", "no overlap", "重なりなし", "sin solapamiento", "nessuna sovrapposizione", "engin skörun", "nulla intersectio"),
    "全屏": _row("全屏", "fullscreen", "全画面", "pantalla completa", "schermo intero", "allur skjár", "totum scrinium"),
    "局部": _row("局部", "local", "ローカル", "local", "locale", "staðbundið", "locale"),
    "交集": _row("交集", "intersection", "交差", "intersección", "intersezione", "skörun", "intersectio"),
    "有效": _row("有效", "effective", "有効", "efectivo", "effettivo", "virkt", "efficax"),
    "：检测输入 → 值=": _row("：检测输入 → 值=", ": inspect input → value=", "：入力検査 → 値=", ": inspeccionar entrada → valor=", ": ispeziona input → valore=", ": skoða inntak → gildi=", ": ingressum inspice → valor="),
    "类型=": _row("类型=", "type=", "型=", "tipo=", "tipo=", "tegund=", "typus="),
    "数据标记=": _row("数据标记=", "data tag=", "データタグ=", "etiqueta de datos=", "tag dati=", "gagnamerki=", "nota datorum="),
    "：执行": _row("：执行", ": execute ", "：実行 ", ": ejecutar ", ": esegui ", ": keyra ", ": exsequere "),
    "输入=": _row("输入=", "input=", "入力=", "entrada=", "ingresso=", "inntak=", "ingressus="),
})


_TRANSLATIONS.update({
    "__anchor_roi_join__": _row("的", "within", "の", "de", "di", "innan", "intra"),
    "，但 ": _row("，但 ", ", but ", "、ただし ", ", pero ", ", ma ", ", en ", ", sed "),
    "必须带有明确的正负号。\n例如：+20 或 -15。": _row(
        "必须带有明确的正负号。\n例如：+20 或 -15。",
        "An explicit positive or negative sign is required.\nFor example: +20 or -15.",
        "正負の符号を明示してください。\n例：+20 または -15。",
        "Se requiere un signo positivo o negativo explícito.\nPor ejemplo: +20 o -15.",
        "È richiesto un segno positivo o negativo esplicito.\nAd esempio: +20 o -15.",
        "Skýrt jákvætt eða neikvætt formerki er nauðsynlegt.\nTil dæmis: +20 eða -15.",
        "Signum positivum vel negativum explicitum requiritur.\nExempli gratia: +20 vel -15."
    ),
    "已存在。\n是否覆盖这个模板？": _row(
        "已存在。\n是否覆盖这个模板？",
        "already exists.\nOverwrite this template?",
        "はすでに存在します。\nこのテンプレートを上書きしますか？",
        "ya existe.\n¿Sobrescribir esta plantilla?",
        "esiste già.\nSovrascrivere questo modello?",
        "er þegar til.\nYfirskrifa þetta sniðmát?",
        "iam exstat.\nHoc exemplar superscribere?"
    ),
    "项目内的工作流、模板和资源都会一起删除。": _row(
        "项目内的工作流、模板和资源都会一起删除。",
        "The project's workflows, templates and resources will all be deleted.",
        "プロジェクト内のワークフロー、テンプレート、リソースもすべて削除されます。",
        "También se eliminarán todos los flujos, plantillas y recursos del proyecto.",
        "Verranno eliminati anche tutti i flussi, modelli e risorse del progetto.",
        "Öllum flæðum, sniðmátum og tilföngum verkefnisins verður einnig eytt.",
        "Omnes fluxus, exemplaria et opes projecti quoque delebuntur."
    ),
    "此操作无法撤销。\n请输入项目名称“": _row(
        "此操作无法撤销。\n请输入项目名称“",
        "This action cannot be undone.\nEnter the project name “",
        "この操作は元に戻せません。\nプロジェクト名「",
        "Esta acción no se puede deshacer.\nIntroduce el nombre del proyecto «",
        "Questa azione non può essere annullata.\nInserisci il nome del progetto «",
        "Ekki er hægt að afturkalla þessa aðgerð.\nSláðu inn verkefnisheitið „",
        "Haec actio revocari non potest.\nNomen projecti «"
    ),
})

_TRANSLATIONS.update({
    "拖动模式": _row("拖动模式", "Drag mode", "ドラッグモード", "Modo de arrastre", "Modalità trascinamento", "Draghamur", "Modus tractus"),
    "坐标至坐标": _row("坐标至坐标", "Coordinate to coordinate", "座標から座標", "Coordenada a coordenada", "Da coordinata a coordinata", "Hnit til hnits", "Coordinata ad coordinatam"),
    "坐标为起始拖动特定像素": _row("坐标为起始拖动特定像素", "Drag specific pixels from coordinate", "座標を起点に指定ピクセル移動", "Arrastrar píxeles desde coordenada", "Trascina pixel dalla coordinata", "Draga tiltekna díla frá hniti", "Pixela definita a coordinata trahe"),
    "模式：坐标至坐标": _row("模式：坐标至坐标", "Mode: Coordinate to coordinate", "モード：座標から座標", "Modo: Coordenada a coordenada", "Modalità: da coordinata a coordinata", "Hamur: hnit til hnits", "Modus: coordinata ad coordinatam"),
    "模式：坐标为起始拖动特定像素": _row("模式：坐标为起始拖动特定像素", "Mode: Drag specific pixels from coordinate", "モード：座標を起点に指定ピクセル移動", "Modo: Arrastrar píxeles desde coordenada", "Modalità: trascina pixel dalla coordinata", "Hamur: draga díla frá hniti", "Modus: pixela a coordinata trahe"),
    "起点坐标": _row("起点坐标", "Start coordinate", "開始座標", "Coordenada inicial", "Coordinata iniziale", "Upphafshnit", "Coordinata initialis"),
    "终点坐标": _row("终点坐标", "End coordinate", "終了座標", "Coordenada final", "Coordinata finale", "Endahnit", "Coordinata finalis"),
    "起点坐标来自拖动模块上方的坐标输入；在这里手动设置终点坐标。": _row(
        "起点坐标来自拖动模块上方的坐标输入；在这里手动设置终点坐标。",
        "The start coordinate comes from the coordinate input above Drag; set the end coordinate here.",
        "開始座標はドラッグ上部の座標入力から取得します。ここで終了座標を設定します。",
        "La coordenada inicial viene de la entrada superior de Arrastrar; define aquí la coordenada final.",
        "La coordinata iniziale proviene dall'ingresso sopra Trascina; imposta qui la coordinata finale.",
        "Upphafshnitið kemur frá hnitainntakinu fyrir ofan Draga; stilltu endahnitið hér.",
        "Coordinata initialis ab ingressu superiore Tractus venit; coordinatam finalem hic constitue."
    ),
    "复杂模式：第一个输入口接入起点坐标，第二个输入口接入终点坐标。": _row(
        "复杂模式：第一个输入口接入起点坐标，第二个输入口接入终点坐标。",
        "Complex mode: the first input receives the start coordinate and the second receives the end coordinate.",
        "複雑モード：1番目の入力が開始座標、2番目の入力が終了座標です。",
        "Modo complejo: la primera entrada recibe la coordenada inicial y la segunda la final.",
        "Modalità complessa: il primo ingresso riceve la coordinata iniziale e il secondo quella finale.",
        "Flókinn hamur: fyrsta inntak er upphafshnit og annað endahnit.",
        "Modus complexus: ingressus primus coordinatam initialem, secundus finalem accipit."
    ),
    "起点坐标来自输入。填写相对起点的像素位移；正负号决定拖动方向。": _row(
        "起点坐标来自输入。填写相对起点的像素位移；正负号决定拖动方向。",
        "The start coordinate comes from the input. Enter pixel offsets relative to it; signs determine drag direction.",
        "開始座標は入力から取得します。開始点からのピクセル差分を入力し、符号で方向を指定します。",
        "La coordenada inicial viene de la entrada. Introduce desplazamientos en píxeles; el signo determina la dirección.",
        "La coordinata iniziale proviene dall'ingresso. Inserisci gli offset in pixel; il segno determina la direzione.",
        "Upphafshnitið kemur frá inntaki. Sláðu inn dílahliðrun; formerki ræður stefnu.",
        "Coordinata initialis ab ingressu venit. Discessus pixelorum insere; signum directionem definit."
    ),
    "终点 X": _row("终点 X", "End X", "終了 X", "X final", "X finale", "Enda X", "X finale"),
    "X 像素": _row("X 像素", "X pixels", "X ピクセル", "Píxeles X", "Pixel X", "X dílar", "Pixela X"),
    "Y 像素": _row("Y 像素", "Y pixels", "Y ピクセル", "Píxeles Y", "Pixel Y", "Y dílar", "Pixela Y"),
    "起点输入": _row("起点输入", "start input", "開始入力", "entrada inicial", "ingresso iniziale", "upphafsinntak", "ingressus initialis"),
    "拖动需要上一个模块提供起点坐标。": _row("拖动需要上一个模块提供起点坐标。", "Drag requires a start coordinate from the previous module.", "ドラッグには前のモジュールからの開始座標が必要です。", "Arrastrar necesita una coordenada inicial del módulo anterior.", "Trascina richiede una coordinata iniziale dal modulo precedente.", "Draga þarf upphafshnit frá fyrri einingu.", "Tractus coordinatam initialem a modulo priore requirit."),
    "复杂模式拖动缺少终点坐标输入。": _row("复杂模式拖动缺少终点坐标输入。", "Complex-mode Drag is missing its end-coordinate input.", "複雑モードのドラッグに終了座標入力がありません。", "A Arrastrar en modo complejo le falta la coordenada final.", "A Trascina in modalità complessa manca la coordinata finale.", "Draga í flóknum ham vantar endahnit.", "Tractui in modo complexo coordinata finalis deest."),
    "拖动终点输入没有输出全局屏幕坐标。": _row("拖动终点输入没有输出全局屏幕坐标。", "Drag end input did not output global screen coordinates.", "ドラッグの終了入力がグローバル画面座標を出力しませんでした。", "La entrada final de Arrastrar no produjo coordenadas globales.", "L'ingresso finale di Trascina non ha prodotto coordinate globali.", "Endainntak Draga skilaði ekki hnattrænum skjáhnitum.", "Ingressus finalis Tractus coordinatas globales scrinii non edidit."),
    "拖动拒绝非全局屏幕起点坐标。": _row("拖动拒绝非全局屏幕起点坐标。", "Drag rejects start coordinates that are not global screen coordinates.", "ドラッグはグローバル画面座標以外の開始座標を受け付けません。", "Arrastrar rechaza coordenadas iniciales que no sean globales.", "Trascina rifiuta coordinate iniziali non globali.", "Draga hafnar upphafshnitum sem eru ekki hnattræn skjáhnit.", "Tractus coordinatas initiales non-globales recusat."),
})


def normalize_language(code: str | None) -> str:
    value = str(code or "zh_CN").strip()
    aliases = {
        "zh": "zh_CN",
        "zh-cn": "zh_CN",
        "zh_cn": "zh_CN",
        "cn": "zh_CN",
        "english": "en",
        "jp": "ja",
        "es_es": "es",
        "it_it": "it",
        "is_is": "is",
        "latin": "la",
    }
    value = aliases.get(value.lower(), value)
    return value if value in _LANGUAGE_CODES else "zh_CN"



_TRANSLATIONS.update({
    "按下": _row("按下", "Mouse down", "マウス押下", "Pulsar ratón", "Pressione mouse", "Mús niðri", "Mus deprime"),
    "抬起": _row("抬起", "Mouse up", "マウス解放", "Soltar ratón", "Rilascia mouse", "Mús upp", "Mus dimitte"),
    "执行鼠标左键按下，不自动抬起。": _row(
        "执行鼠标左键按下，不自动抬起。",
        "Press and hold the left mouse button without releasing it automatically.",
        "左マウスボタンを押し下げます。自動では離しません。",
        "Presiona y mantiene el botón izquierdo del ratón sin soltarlo automáticamente.",
        "Preme e tiene premuto il tasto sinistro del mouse senza rilasciarlo automaticamente.",
        "Ýtir niður vinstri músarhnappinum án þess að sleppa honum sjálfkrafa.",
        "Bullam musis sinistrum deprimit et retinet neque sponte dimittit."
    ),
    "执行鼠标左键抬起。": _row(
        "执行鼠标左键抬起。",
        "Release the left mouse button.",
        "左マウスボタンを離します。",
        "Suelta el botón izquierdo del ratón.",
        "Rilascia il tasto sinistro del mouse.",
        "Sleppir vinstri músarhnappinum.",
        "Bullam musis sinistrum dimittit."
    ),
})

_TRANSLATIONS.update({
    "左键": _row("左键", "Left button", "左ボタン", "Botón izquierdo", "Tasto sinistro", "Vinstri hnappur", "Bulla sinistra"),
    "右键": _row("右键", "Right button", "右ボタン", "Botón derecho", "Tasto destro", "Hægri hnappur", "Bulla dextra"),
    "中键": _row("中键", "Middle button", "中ボタン", "Botón central", "Tasto centrale", "Miðhnappur", "Bulla media"),
    "鼠标按键": _row("鼠标按键", "Mouse button", "マウスボタン", "Botón del ratón", "Pulsante del mouse", "Músarhnappur", "Bulla musis"),
    "按下设置": _row("按下设置", "Mouse down settings", "マウス押下設定", "Ajustes de pulsación", "Impostazioni pressione mouse", "Stillingar músarhnapps niður", "Configurationes depressionis musis"),
    "抬起设置": _row("抬起设置", "Mouse up settings", "マウス解放設定", "Ajustes de liberación", "Impostazioni rilascio mouse", "Stillingar músarhnapps upp", "Configurationes remissionis musis"),
    "按下会保持鼠标按键处于按住状态，直到遇到对应的抬起模块。": _row(
        "按下会保持鼠标按键处于按住状态，直到遇到对应的抬起模块。",
        "Mouse down keeps the selected button held until a matching Mouse up module releases it.",
        "マウス押下は、対応するマウス解放モジュールまで選択したボタンを押したままにします。",
        "Mouse down mantiene pulsado el botón seleccionado hasta que un módulo Mouse up correspondiente lo libere.",
        "Mouse down mantiene premuto il pulsante selezionato finché un modulo Mouse up corrispondente non lo rilascia.",
        "Mús niður heldur völdum hnappi niðri þar til samsvarandi Mús upp eining sleppir honum.",
        "Mus deprime bullam electam retinet donec modulus congruus Mus dimitte eam solvat."
    ),
    "抬起会释放所选择的鼠标按键。": _row(
        "抬起会释放所选择的鼠标按键。",
        "Mouse up releases the selected mouse button.",
        "マウス解放は選択したマウスボタンを離します。",
        "Mouse up suelta el botón del ratón seleccionado.",
        "Mouse up rilascia il pulsante del mouse selezionato.",
        "Mús upp sleppir völdum músarhnappi.",
        "Mus dimitte bullam musis electam solvit."
    ),
    "执行所选鼠标按键的按下动作，不自动抬起。": _row(
        "执行所选鼠标按键的按下动作，不自动抬起。",
        "Press the selected mouse button without releasing it automatically.",
        "選択したマウスボタンを押し下げ、自動では離しません。",
        "Pulsa el botón del ratón seleccionado sin soltarlo automáticamente.",
        "Preme il pulsante del mouse selezionato senza rilasciarlo automaticamente.",
        "Ýtir niður völdum músarhnappi án þess að sleppa honum sjálfkrafa.",
        "Bullam musis electam deprimit neque sponte dimittit."
    ),
    "执行所选鼠标按键的抬起动作。": _row(
        "执行所选鼠标按键的抬起动作。",
        "Release the selected mouse button.",
        "選択したマウスボタンを離します。",
        "Suelta el botón del ratón seleccionado.",
        "Rilascia il pulsante del mouse selezionato.",
        "Sleppir völdum músarhnappi.",
        "Bullam musis electam dimittit."
    ),
})

_TRANSLATIONS.update({
    "鼠标按下": _row("鼠标按下", "Mouse down", "マウス押下", "Pulsar ratón", "Pressione mouse", "Mús niður", "Mus deprime"),
    "鼠标抬起": _row("鼠标抬起", "Mouse up", "マウス解放", "Soltar ratón", "Rilascio mouse", "Mús upp", "Mus dimitte"),
    "鼠标按下失败": _row("鼠标按下失败", "Mouse down failed", "マウス押下に失敗", "Falló la pulsación del ratón", "Pressione mouse non riuscita", "Mús niður mistókst", "Depressio musis defecit"),
    "鼠标抬起失败": _row("鼠标抬起失败", "Mouse up failed", "マウス解放に失敗", "Falló la liberación del ratón", "Rilascio mouse non riuscito", "Mús upp mistókst", "Remissio musis defecit"),
})

def current_language() -> str:
    return _CURRENT_LANGUAGE


def _reverse_index() -> dict[str, str]:
    reverse: dict[str, str] = {}
    for source, row in _TRANSLATIONS.items():
        reverse[source] = source
        for translated in row.values():
            if translated:
                reverse.setdefault(translated, source)
    return reverse


_REVERSE = _reverse_index()


def tr_text(
    text: Any,
    language: str | None = None,
) -> str:
    raw = str(text)

    if not raw:
        return raw

    language = normalize_language(
        language
        or _CURRENT_LANGUAGE
    )

    # Exact translations support switching from any already-translated
    # language to any other language.
    source = _REVERSE.get(
        raw,
        raw,
    )
    row = _TRANSLATIONS.get(
        source
    )

    if row is not None:
        return row.get(
            language,
            row.get(
                "en",
                source,
            ),
        )

    # Dynamic labels in UVAF are normally authored in Chinese and contain
    # runtime values such as coordinates, filenames or counts. Translate all
    # known source fragments while preserving those runtime values.
    if (
        language != "zh_CN"
        and _CJK_RE.search(
            raw
        )
    ):
        return _translate_dynamic_chinese(
            raw,
            language,
        )

    return raw


def _translate_action(action: QAction) -> None:
    if action.isSeparator():
        return
    action.setText(tr_text(action.text()))


def translate_widget_tree(root: QWidget | None) -> None:
    if root is None:
        return

    if isinstance(root, QDialog):
        root.setWindowTitle(tr_text(root.windowTitle()))

    widgets = [root, *root.findChildren(QWidget)]

    for widget in widgets:
        if isinstance(widget, QLabel):
            widget.setText(tr_text(widget.text()))
        elif isinstance(widget, QAbstractButton):
            widget.setText(tr_text(widget.text()))
        elif isinstance(widget, QGroupBox):
            widget.setTitle(tr_text(widget.title()))
        elif isinstance(widget, QComboBox):
            for index in range(widget.count()):
                widget.setItemText(index, tr_text(widget.itemText(index)))
        elif isinstance(widget, QLineEdit):
            placeholder = widget.placeholderText()
            if placeholder:
                widget.setPlaceholderText(tr_text(placeholder))
        elif isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                widget.setTabText(index, tr_text(widget.tabText(index)))
        elif isinstance(widget, QListWidget):
            for index in range(widget.count()):
                item = widget.item(index)
                item.setText(tr_text(item.text()))
        elif isinstance(widget, QTableWidget):
            for column in range(widget.columnCount()):
                item = widget.horizontalHeaderItem(column)
                if item is not None:
                    item.setText(
                        tr_text(
                            item.text()
                        )
                    )

            for row in range(widget.rowCount()):
                vertical_item = (
                    widget.verticalHeaderItem(
                        row
                    )
                )

                if vertical_item is not None:
                    vertical_item.setText(
                        tr_text(
                            vertical_item.text()
                        )
                    )

                for column in range(
                    widget.columnCount()
                ):
                    item = widget.item(
                        row,
                        column,
                    )

                    if item is not None:
                        item.setText(
                            tr_text(
                                item.text()
                            )
                        )
        elif isinstance(widget, QMenu):
            for action in widget.actions():
                _translate_action(action)

    for action in root.findChildren(QAction):
        _translate_action(action)


class _I18nEventFilter(QObject):
    def eventFilter(self, watched, event) -> bool:
        if event.type() in {
            QEvent.Show,
            QEvent.Polish,
        } and isinstance(watched, QWidget):
            translate_widget_tree(watched)
        return False


def install_i18n(app: QApplication, language: str = "zh_CN") -> None:
    global _CURRENT_LANGUAGE
    _CURRENT_LANGUAGE = normalize_language(language)

    event_filter = getattr(app, "_uvaf_i18n_filter", None)
    if event_filter is None:
        event_filter = _I18nEventFilter(app)
        app._uvaf_i18n_filter = event_filter
        app.installEventFilter(event_filter)

    for widget in app.topLevelWidgets():
        translate_widget_tree(widget)


def set_language(language: str, root: QWidget | None = None) -> None:
    global _CURRENT_LANGUAGE
    _CURRENT_LANGUAGE = normalize_language(language)

    app = QApplication.instance()
    if app is not None:
        if getattr(app, "_uvaf_i18n_filter", None) is None:
            install_i18n(app, _CURRENT_LANGUAGE)
        for widget in app.topLevelWidgets():
            translate_widget_tree(widget)

    if root is not None:
        translate_widget_tree(root)
