# Code version: 2026-09-22 08:35
from pathlib import Path
from collections import Counter
from difflib import get_close_matches
import re
import threading

from gi.repository import Gtk, GLib, Pango

from zim.plugins import PluginClass
from zim.actions import action
from zim.gui.mainwindow import MainWindowExtension
from zim.newfs import LocalFile
from zim.config import ConfigManager

import enchant

def _apply_zim_text_font(textview):
    """
    Применяет к Gtk.TextView шрифт,
    заданный в настройках текста Zim.
    """

    text_style = ConfigManager.get_config_dict(
        'style.conf'
    )

    font_name = (
        text_style['TextView'].get(
            'font'
        )
    )

    if not font_name:
        textview.modify_font(
            None
        )
        return

    font = Pango.FontDescription(
        font_name
    )

    textview.modify_font(
        font
    )

class SpellCheckerPlugin(PluginClass):

    plugin_info = {
        'name': 'Spell Checker',
        'description': 'Check spelling in notebook pages',
        'author': 'Nick',
    }


class SpellCheckerMainWindowExtension(MainWindowExtension):

    def __init__(self, plugin, window):
        super().__init__(plugin, window)

        self.check_window = None

        self.check_thread = None
        self.stop_event = None

        self.files = []
        self.checked = 0

        # word -> list of (filename, line_number, line_text)
        self.errors = {}

        self.current_word = None
        self.current_occurrence = 0

        self.pending_replacement = None

        self.current_filename = None

        self.dictionary = None

        self.corpus = Counter()

        self.updating_model = False

    # =====================================================
    # Window
    # =====================================================

    @action('Проверка орфографии', menuhints='tools')
    def spell_check(self):

        if self.check_window is not None:
            self.check_window.present()
            return

        self.check_window = Gtk.Window(
            title='Проверка орфографии'
        )

        self.check_window.set_default_size(
            1100,
            700
        )

        self.check_window.set_position(
            Gtk.WindowPosition.CENTER
        )

        self.check_window.connect(
            'destroy',
            self._on_window_destroy
        )

        vbox = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6
        )

        vbox.set_border_width(10)

        self.check_window.add(vbox)

        # -------------------------------------------------
        # Controls
        # -------------------------------------------------

        controls = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6
        )

        self.check_button = Gtk.Button(
            label='Проверить'
        )

        self.check_button.connect(
            'clicked',
            self._start_check
        )

        controls.pack_start(
            self.check_button,
            False,
            False,
            0
        )

        self.stop_button = Gtk.Button(
            label='Остановить'
        )

        self.stop_button.set_sensitive(
            False
        )

        self.stop_button.connect(
            'clicked',
            self._stop_check
        )

        controls.pack_start(
            self.stop_button,
            False,
            False,
            0
        )

        self.status_label = Gtk.Label(
            label='Готово'
        )

        self.status_label.set_xalign(
            0
        )

        controls.pack_start(
            self.status_label,
            True,
            True,
            0
        )

        vbox.pack_start(
            controls,
            False,
            False,
            0
        )

        # -------------------------------------------------
        # Word list
        # -------------------------------------------------

        self.model = Gtk.ListStore(
            str,     # 0 word
            int,     # 1 count
        )

        self.tree = Gtk.TreeView(
            model=self.model
        )

        self._add_column(
            'Слово',
            0,
            expand=True
        )

        self._add_column(
            'Мест',
            1
        )

        self.tree.connect(
            'cursor-changed',
            self._word_selected
        )

        # -------------------------------------------------
        # Word search
        # -------------------------------------------------

        search_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6
        )

        search_label = Gtk.Label(
            label='Поиск:'
        )

        search_box.pack_end(
            search_label,
            False,
            False,
            0
        )

        self.word_search = Gtk.SearchEntry()

        self.word_search.set_placeholder_text(
            'Искать слово...'
        )

        self.word_search.connect(
            'search-changed',
            self._search_word
        )

        search_box.pack_end(
            self.word_search,
            False,
            False,
            0
        )

        vbox.pack_start(
            search_box,
            False,
            False,
            0
        )

        scroll = Gtk.ScrolledWindow()

        scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC,
            Gtk.PolicyType.AUTOMATIC
        )

        scroll.set_min_content_height(
            300
        )

        scroll.add(
            self.tree
        )

        vbox.pack_start(
            scroll,
            True,
            True,
            0
        )

        # -------------------------------------------------
        # Selected word
        # -------------------------------------------------

        self.word_label = Gtk.Label(
            label=''
        )

        self.word_label.set_xalign(
            0
        )

        vbox.pack_start(
            self.word_label,
            False,
            False,
            0
        )

        # -------------------------------------------------
        # Context
        # -------------------------------------------------

        self.filename_label = Gtk.Label(
            label=''
        )

        self.filename_label.set_xalign(
            0
        )

        vbox.pack_start(
            self.filename_label,
            False,
            False,
            0
        )

        self.context_view = Gtk.TextView()

        self.context_view.set_editable(
            False
        )

        self.context_view.set_cursor_visible(
            False
        )

        self.context_view.set_wrap_mode(
            Gtk.WrapMode.NONE
        )

        _apply_zim_text_font(
            self.context_view
        )

        buffer = self.context_view.get_buffer()

        self.error_tag = buffer.create_tag(
            'error_word',
            foreground='#66aaff',
            weight=Pango.Weight.BOLD
        )

        context_scroll = Gtk.ScrolledWindow()

        context_scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC,
            Gtk.PolicyType.AUTOMATIC
        )

        context_scroll.set_min_content_height(
            180
        )

        context_scroll.add(
            self.context_view
        )

        vbox.pack_start(
            context_scroll,
            True,
            True,
            0
        )

        # -------------------------------------------------
        # Suggestions
        # -------------------------------------------------

        suggestions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12
        )

        corpus_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=3
        )

        corpus_label = Gtk.Label(
            label='Из вашего корпуса:'
        )

        corpus_label.set_xalign(
            0
        )

        corpus_box.pack_start(
            corpus_label,
            False,
            False,
            0
        )

        self.corpus_model = Gtk.ListStore(
            str
        )

        self.corpus_tree = Gtk.TreeView(
            model=self.corpus_model
        )

        self._add_suggestion_column(
            self.corpus_tree
        )

        self.corpus_tree.connect(
            'cursor-changed',
            self._corpus_suggestion_selected
        )

        corpus_scroll = Gtk.ScrolledWindow()

        corpus_scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC,
            Gtk.PolicyType.AUTOMATIC
        )

        corpus_scroll.set_min_content_height(
            100
        )

        corpus_scroll.add(
            self.corpus_tree
        )

        corpus_box.pack_start(
            corpus_scroll,
            True,
            True,
            0
        )

        dictionary_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=3
        )

        dictionary_label = Gtk.Label(
            label='Из словаря:'
        )

        dictionary_label.set_xalign(
            0
        )

        dictionary_box.pack_start(
            dictionary_label,
            False,
            False,
            0
        )

        self.dictionary_model = Gtk.ListStore(
            str
        )

        self.dictionary_tree = Gtk.TreeView(
            model=self.dictionary_model
        )

        self._add_suggestion_column(
            self.dictionary_tree
        )

        self.dictionary_tree.connect(
            'cursor-changed',
            self._dictionary_suggestion_selected
        )

        dictionary_scroll = Gtk.ScrolledWindow()

        dictionary_scroll.set_policy(
            Gtk.PolicyType.AUTOMATIC,
            Gtk.PolicyType.AUTOMATIC
        )

        dictionary_scroll.set_min_content_height(
            100
        )

        dictionary_scroll.add(
            self.dictionary_tree
        )

        dictionary_box.pack_start(
            dictionary_scroll,
            True,
            True,
            0
        )

        suggestions.pack_start(
            corpus_box,
            True,
            True,
            0
        )

        suggestions.pack_start(
            dictionary_box,
            True,
            True,
            0
        )

        vbox.pack_start(
            suggestions,
            False,
            True,
            0
        )

        replacement_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=8
        )

        self.replace_button = Gtk.Button(
            label='Заменить'
        )

        self.replace_button.set_sensitive(
            False
        )

        self.replace_button.connect(
            'clicked',
            self._replace_selected_suggestion
        )

        replacement_box.pack_start(
            self.replace_button,
            False,
            False,
            0
        )

        self.replacement_status_label = Gtk.Label(
            label=''
        )

        self.replacement_status_label.set_xalign(
            0
        )

        replacement_box.pack_start(
            self.replacement_status_label,
            True,
            True,
            0
        )

        vbox.pack_start(
            replacement_box,
            False,
            False,
            0
        )

        # -------------------------------------------------
        # Navigation
        # -------------------------------------------------

        navigation = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6
        )

        self.previous_button = Gtk.Button(
            label='Предыдущее место'
        )

        self.previous_button.set_sensitive(
            False
        )

        self.previous_button.connect(
            'clicked',
            self._previous_occurrence
        )

        navigation.pack_start(
            self.previous_button,
            False,
            False,
            0
        )

        self.next_button = Gtk.Button(
            label='Следующее место'
        )

        self.next_button.set_sensitive(
            False
        )

        self.next_button.connect(
            'clicked',
            self._next_occurrence
        )

        navigation.pack_start(
            self.next_button,
            False,
            False,
            0
        )

        self.open_button = Gtk.Button(
            label='Открыть заметку'
        )

        self.open_button.set_sensitive(
            False
        )

        self.open_button.connect(
            'clicked',
            self._open_current_note
        )

        navigation.pack_start(
            self.open_button,
            False,
            False,
            0
        )

        self.recheck_word_button = Gtk.Button(
            label='Перепроверить слово'
        )

        self.recheck_word_button.set_sensitive(
            False
        )

        self.recheck_word_button.connect(
            'clicked',
            self._recheck_word
        )

        navigation.pack_start(
            self.recheck_word_button,
            False,
            False,
            0
        )

        self.recheck_note_button = Gtk.Button(
            label='Перепроверить заметку'
        )

        self.recheck_note_button.set_sensitive(
            False
        )

        self.recheck_note_button.connect(
            'clicked',
            self._recheck_note
        )

        navigation.pack_start(
            self.recheck_note_button,
            False,
            False,
            0
        )

        vbox.pack_start(
            navigation,
            False,
            False,
            0
        )

        # -------------------------------------------------
        # Decision
        # -------------------------------------------------

        decisions = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=6
        )

        self.add_button = Gtk.Button(
            label='Добавить в словарь'
        )

        self.add_button.set_sensitive(
            False
        )

        self.add_button.connect(
            'clicked',
            self._add_word_to_dictionary
        )

        decisions.pack_start(
            self.add_button,
            False,
            False,
            0
        )

        self.ignore_button = Gtk.Button(
            label='Пропустить слово'
        )

        self.ignore_button.set_sensitive(
            False
        )

        self.ignore_button.connect(
            'clicked',
            self._ignore_word
        )

        decisions.pack_start(
            self.ignore_button,
            False,
            False,
            0
        )

        vbox.pack_start(
            decisions,
            False,
            False,
            0
        )

        self.check_window.show_all()

    # =====================================================
    # Columns
    # =====================================================

    def _add_column(
        self,
        title,
        index,
        expand=False
    ):

        renderer = Gtk.CellRendererText()

        column = Gtk.TreeViewColumn(
            title,
            renderer,
            text=index
        )

        column.set_sort_column_id(
            index
        )

        if expand:
            column.set_expand(
                True
            )

        self.tree.append_column(
            column
        )

    def _add_suggestion_column(
        self,
        tree
    ):

        renderer = Gtk.CellRendererText()

        column = Gtk.TreeViewColumn(
            'Вариант',
            renderer,
            text=0
        )

        tree.append_column(
            column
        )

    # =====================================================
    # Start
    # =====================================================

    def _start_check(self, button):

        if (
            self.check_thread is not None
            and self.check_thread.is_alive()
        ):
            return

        self.model.clear()

        self.errors = {}

        self.current_word = None
        self.current_occurrence = 0

        self.corpus = Counter()

        root = Path(
            self.window.notebook.folder.path
        )

        self.files = list(
            root.rglob('*.txt')
        )

        self.checked = 0

        self.stop_event = threading.Event()

        self.check_button.set_sensitive(
            False
        )

        self.stop_button.set_sensitive(
            True
        )

        self.status_label.set_text(
            'Начинаю проверку...'
        )

        self._clear_context()

        self.check_thread = threading.Thread(
            target=self._check_notebook,
            daemon=True
        )

        self.check_thread.start()

    # =====================================================
    # Stop
    # =====================================================

    def _stop_check(self, button):

        if self.stop_event is not None:
            self.stop_event.set()

        self.status_label.set_text(
            'Остановка...'
        )

        self.stop_button.set_sensitive(
            False
        )

    # =====================================================
    # Background check
    # =====================================================

    def _check_notebook(self):

        try:
            self.dictionary = enchant.Dict(
                'ru_RU'
            )

            total = len(self.files)

            for filename in self.files:

                if self.stop_event.is_set():
                    break

                self._check_file(
                    filename,
                    self.dictionary,
                )

                self.checked += 1

                GLib.idle_add(
                    self._update_progress,
                    self.checked,
                    total
                )

            words_file = Path(
                'spell_checker_words.txt'
            )

            with words_file.open(
                'w',
                encoding='utf-8'
            ) as output:

                for word in sorted(self.errors):
                    output.write(
                        word + '\n'
                    )

        except Exception as error:

            GLib.idle_add(
                self._show_background_error,
                str(error)
            )

        finally:

            GLib.idle_add(
                self._check_finished
            )

    # =====================================================
    # Check one file
    # =====================================================

    def _check_file(
        self,
        filename,
        dictionary,
    ):

        try:
            text = filename.read_text(
                encoding='utf-8'
            )
        except Exception:
            return

        lines = text.splitlines()

        # Пропускаем служебный Zim header.
        content_started = False

        for line_number, original_line in enumerate(
            lines,
            start=1
        ):

            if self.stop_event.is_set():
                return

            if not content_started:

                if not original_line.strip():
                    content_started = True

                continue

            # Заголовки Zim.
            if re.search(
                r'={2,}',
                original_line
            ):
                continue

            # Убираем [[...]]
            line = re.sub(
                r'\[\[.*?\]\]',
                ' ',
                original_line
            )

            words = re.findall(
                r"[A-Za-zА-Яа-яЁё]+(?:[-'][A-Za-zА-Яа-яЁё]+)*",
                line
            )

            for word in words:

                if self.stop_event.is_set():
                    return

                if len(word) >= 3:
                    self.corpus[word] += 1

                if dictionary.check(word):
                    continue

                if word not in self.errors:
                    self.errors[word] = []

                self.errors[word].append(
                    (
                        filename,
                        line_number,
                        original_line
                    )
                )

    # =====================================================
    # Progress
    # =====================================================

    def _update_progress(
        self,
        checked,
        total
    ):

        if self.stop_event is not None:
            if self.stop_event.is_set():
                return False

        errors = sum(
            len(items)
            for items in self.errors.values()
        )

        self.status_label.set_text(
            'Проверено: {} / {}    '
            'Ошибок: {}    '
            'Уникальных слов: {}'.format(
                checked,
                total,
                errors,
                len(self.errors)
            )
        )

        return False

    # =====================================================
    # Finished
    # =====================================================

    def _check_finished(self):

        if self.check_window is None:
            return False

        stopped = (
            self.stop_event is not None
            and self.stop_event.is_set()
        )

        self.updating_model = True

        self.model.clear()

        # Сортируем слова.
        words = sorted(
            self.errors.keys(),
            key=lambda word: word.lower()
        )

        for word in words:
            self.model.append(
                [
                    word,
                    len(self.errors[word])
                ]
            )

        self.updating_model = False

        if stopped:

            self.status_label.set_text(
                'Остановлено: {} / {}    '
                'Ошибок: {}    '
                'Уникальных слов: {}'.format(
                    self.checked,
                    len(self.files),
                    sum(
                        len(items)
                        for items in self.errors.values()
                    ),
                    len(self.errors)
                )
            )

        else:

            self.status_label.set_text(
                'Готово: {} файлов    '
                'Ошибок: {}    '
                'Уникальных слов: {}'.format(
                    self.checked,
                    sum(
                        len(items)
                        for items in self.errors.values()
                    ),
                    len(self.errors)
                )
            )

        self.check_button.set_sensitive(
            True
        )

        self.stop_button.set_sensitive(
            False
        )

        self.check_thread = None

        return False

    # =====================================================
    # Search word
    # =====================================================

    def _search_word(self, entry):

        text = entry.get_text().strip().lower()

        if not text:
            return

        for iterator in self.model:

            word = iterator[0]

            if text in word.lower():

                path = iterator.path

                self.tree.set_cursor(
                    path,
                    None,
                    False
                )

                self.tree.scroll_to_cell(
                    path,
                    None,
                    False,
                    0.0,
                    0.0
                )

                return

    # =====================================================
    # Word selected
    # =====================================================

    def _word_selected(self, tree):

        if self.updating_model:
            return

        selection = tree.get_selection()

        model, iterator = selection.get_selected()

        if iterator is None:
            return

        word = model[iterator][0]

        self.current_word = word
        self.current_occurrence = 0

        self._show_current_occurrence()

    # =====================================================
    # Show occurrence
    # =====================================================

    def _show_current_occurrence(self):

        word = self.current_word

        self.pending_replacement = None

        self.replace_button.set_sensitive(
            False
        )

        self.replacement_status_label.set_text(
            ''
        )

        if word is None:
            return

        self._show_suggestions(
            word
        )

        occurrences = self.errors.get(
            word,
            []
        )

        if not occurrences:
            self._clear_context()
            return

        if self.current_occurrence >= len(occurrences):
            self.current_occurrence = (
                len(occurrences) - 1
            )

        filename, line_number, line = (
            occurrences[
                self.current_occurrence
            ]
        )

        self.current_filename = filename

        self.word_label.set_text(
            '{} — место {} из {}'.format(
                word,
                self.current_occurrence + 1,
                len(occurrences)
            )
        )

        # -------------------------------------------------
        # Context: several lines around the occurrence
        # -------------------------------------------------

        try:
            all_lines = filename.read_text(
                encoding='utf-8'
            ).splitlines()

            start = max(
                0,
                line_number - 2
            )

            end = min(
                len(all_lines),
                line_number + 1
            )

            context = []

            for index in range(
                start,
                end
            ):

                number = index + 1

                marker = (
                    '>>> '
                    if number == line_number
                    else '    '
                )

                source_line = all_lines[index]

                if number == line_number:

                    pattern = re.compile(
                        r'(?<![A-Za-zА-Яа-яЁё])'
                        + re.escape(word)
                        + r'(?![A-Za-zА-Яа-яЁё])',
                        0
                    )

                    matches = list(
                        pattern.finditer(
                            source_line
                        )
                    )

                    # Считаем, какое по счёту
                    # вхождение слова находится
                    # в этой строке.
                    line_occurrence = 0

                    for occurrence in occurrences[
                        :self.current_occurrence
                    ]:

                        if (
                            occurrence[0] == filename
                            and occurrence[1] == line_number
                        ):
                            line_occurrence += 1

                    self.current_line_occurrence = line_occurrence

                    if matches:

                        match_index = min(
                            line_occurrence,
                            len(matches) - 1
                        )

                        match = matches[
                            match_index
                        ]

                        left = max(
                            0,
                            match.start() - 50
                        )

                        right = min(
                            len(source_line),
                            match.end() + 50
                        )

                        # Запоминаем смещение отображаемого фрагмента
                        display_prefix = '...' if left > 0 else ''

                        source_line = (
                            display_prefix
                            + source_line[left:right]
                            + ('...' if right < len(source_line) else '')
                        )

                context.append(
                    '{}{:6}: {}'.format(
                        marker,
                        number,
                        source_line
                    )
                )

            self.filename_label.set_text(
                str(filename)
            )

            text = '\n'.join(context)

        except Exception:

            self.filename_label.set_text(
                '{}:{}'.format(
                    filename,
                    line_number
                )
            )

            buffer = self.context_view.get_buffer()
            buffer.set_text(
                line
            )

            return

        buffer = self.context_view.get_buffer()

        buffer.set_text(text)

        # Выделяем найденное слово в текущей строке.
        selected_context_index = (
            line_number - 1 - start
        )

        selected_context_line = context[
            selected_context_index
        ]

        line_start = 0

        if selected_context_index > 0:
            line_start = len(
                '\n'.join(
                    context[
                        :selected_context_index
                    ]
                )
            ) + 1

        # Ищем слово уже в реально отображаемой
        # строке предпросмотра.
        display_matches = list(
            pattern.finditer(
                selected_context_line
            )
        )

        if display_matches:

            display_match_index = min(
                self.current_line_occurrence,
                len(display_matches) - 1
            )

            display_match = display_matches[
                display_match_index
            ]

            word_start = (
                line_start
                + display_match.start()
            )

            word_end = (
                line_start
                + display_match.end()
            )

            start_iter = buffer.get_iter_at_offset(
                word_start
            )

            end_iter = buffer.get_iter_at_offset(
                word_end
            )

            buffer.apply_tag(
                self.error_tag,
                start_iter,
                end_iter
            )

            self.context_view.scroll_to_iter(
                start_iter,
                0.2,
                False,
                0.0,
                0.0
            )

        self.previous_button.set_sensitive(
            self.current_occurrence > 0
        )

        self.next_button.set_sensitive(
            self.current_occurrence <
            len(occurrences) - 1
        )

        self.open_button.set_sensitive(
            True
        )

        self.add_button.set_sensitive(
            True
        )

        self.recheck_word_button.set_sensitive(
            True
        )

        self.recheck_note_button.set_sensitive(
            True
        )

        self.ignore_button.set_sensitive(
            True
        )

    # =====================================================
    # Suggestions
    # =====================================================

    def _get_corpus_suggestions(
        self,
        word,
        limit=15
    ):

        if len(word) < 3:
            return []

        lower_word = word.lower()

        vocabulary = sorted({
            candidate.lower()
            for candidate in self.corpus
            if candidate.lower() != lower_word
        })

        matches = get_close_matches(
            lower_word,
            vocabulary,
            n=limit,
            cutoff=0.55
        )

        result = []

        for matched in matches:

            candidates = [
                candidate
                for candidate in self.corpus
                if candidate.lower() == matched
            ]

            candidates.sort(
                key=lambda candidate: (
                    candidate[0].isupper()
                    != word[0].isupper(),
                    -self.corpus[candidate]
                )
            )

            if candidates:
                result.append(
                    candidates[0]
                )

        return result

    def _show_suggestions(
        self,
        word
    ):

        self.corpus_model.clear()
        self.dictionary_model.clear()

        if word is None:
            return

        for candidate in self._get_corpus_suggestions(
            word
        ):

            self.corpus_model.append(
                [candidate]
            )

        if len(word) >= 3:

            suggestions = self.dictionary.suggest(
                word
            )

            for candidate in suggestions:

                self.dictionary_model.append(
                    [candidate]
                )

    def _corpus_suggestion_selected(
        self,
        tree
    ):

        selection = tree.get_selection()

        model, iterator = selection.get_selected()

        if iterator is None:
            return

        replacement = model[iterator][0]

        self.pending_replacement = replacement

        self.replace_button.set_sensitive(
            True
        )

        self.replacement_status_label.set_text(
            'Выбрано: {}'.format(
                replacement
            )
        )

    def _dictionary_suggestion_selected(
        self,
        tree
    ):

        selection = tree.get_selection()

        model, iterator = selection.get_selected()

        if iterator is None:
            return

        replacement = model[iterator][0]

        self.pending_replacement = replacement

        self.replace_button.set_sensitive(
            True
        )

        self.replacement_status_label.set_text(
            'Выбрано: {}'.format(
                replacement
            )
        )

    def _replace_selected_suggestion(
        self,
        button
    ):

        replacement = self.pending_replacement

        if replacement is None:
            return

        self.pending_replacement = None

        self.replace_button.set_sensitive(
            False
        )

        self._replace_current_occurrence(
            replacement
        )

        self.replacement_status_label.set_text(
            'Заменено'
        )

    def _replace_current_occurrence(
        self,
        replacement
    ):

        if self.current_word is None:
            return

        old_word = self.current_word

        self._open_note(
            self.current_filename
        )

        textview = self.window.pageview.textview
        buffer = textview.get_buffer()

        selection = buffer.get_selection_bounds()

        if not selection:
            return

        start_iter, end_iter = selection

        buffer.delete(
            start_iter,
            end_iter
        )

        buffer.insert(
            start_iter,
            replacement
        )

        # Удаляем только текущее вхождение
        # из списка ошибок.
        occurrences = self.errors.get(
            old_word,
            []
        )

        if self.current_occurrence < len(occurrences):
            del occurrences[
                self.current_occurrence
            ]

        # Если ошибок этого слова больше нет —
        # убираем слово целиком.
        if not occurrences:

            self.errors.pop(
                old_word,
                None
            )

            self.current_word = None
            self.current_occurrence = 0

            self._rebuild_word_list()
            self._clear_context()

            return

        # Ошибки этого слова ещё есть.
        self.current_occurrence = min(
            self.current_occurrence,
            len(occurrences) - 1
        )

        self._rebuild_word_list()

        # Сразу показываем следующее оставшееся
        # вхождение этого же ошибочного слова.
        self._show_current_occurrence()

    # =====================================================
    # Navigation
    # =====================================================

    def _previous_occurrence(self, button):

        if self.current_word is None:
            return

        if self.current_occurrence <= 0:
            return

        self.current_occurrence -= 1

        self._show_current_occurrence()

    def _next_occurrence(self, button):

        if self.current_word is None:
            return

        occurrences = self.errors.get(
            self.current_word,
            []
        )

        if self.current_occurrence >= len(
            occurrences
        ) - 1:
            return

        self.current_occurrence += 1

        self._show_current_occurrence()

    # =====================================================
    # Add to dictionary
    # =====================================================

    def _add_word_to_dictionary(self, button):

        if self.current_word is None:
            return

        word = self.current_word

        try:
            if self.dictionary is None:
                self.dictionary = enchant.Dict(
                    'ru_RU'
                )

            self.dictionary.add(
                word
            )

        except Exception as error:

            self._show_background_error(
                'Не удалось добавить слово:\n{}'.format(
                    error
                )
            )

            return

        # Убираем слово из текущего списка.
        self.errors.pop(
            word,
            None
        )

        self.current_word = None
        self.current_occurrence = 0

        self._rebuild_word_list()

        self._clear_context()

    # =====================================================
    # Ignore word
    # =====================================================

    def _ignore_word(self, button):

        if self.current_word is None:
            return

        word = self.current_word

        # Только убираем из текущей проверки.
        # В словарь ничего не записываем.
        self.errors.pop(
            word,
            None
        )

        self.current_word = None
        self.current_occurrence = 0

        self._rebuild_word_list()

        self._clear_context()

    # =====================================================
    # Rebuild word list
    # =====================================================

    def _rebuild_word_list(self):

        current_word = self.current_word

        self.updating_model = True

        self.model.clear()

        words = sorted(
            self.errors.keys(),
            key=lambda word: word.lower()
        )

        current_iter = None

        for word in words:

            tree_iter = self.model.append(
                [word, len(self.errors[word])]
            )

            if word == current_word:
                current_iter = tree_iter

        self.updating_model = False

        self.status_label.set_text(
            'Осталось уникальных слов: {}'.format(
                len(self.errors)
            )
        )

        if current_iter is not None:

            path = self.model.get_path(
                current_iter
            )

            self.tree.set_cursor(
                path
            )

    # =====================================================
    # Clear context
    # =====================================================

    def _clear_context(self):

        buffer = self.context_view.get_buffer()

        buffer.set_text(
            ''
        )

        self.word_label.set_text(
            ''
        )

        self.filename_label.set_text(
            ''
        )

        self.current_filename = None

        self.previous_button.set_sensitive(
            False
        )

        self.next_button.set_sensitive(
            False
        )

        self.open_button.set_sensitive(
            False
        )

        self.recheck_word_button.set_sensitive(
            False
        )

        self.recheck_note_button.set_sensitive(
            False
        )

        self.add_button.set_sensitive(
            False
        )

        self.ignore_button.set_sensitive(
            False
        )

    # =====================================================
    # Recheck word
    # =====================================================

    def _recheck_word(self, button):

        if self.current_word is None:
            return

        word = self.current_word

        try:
            if self.dictionary is None:
                self.dictionary = enchant.Dict(
                    'ru_RU'
                )

            # Удаляем старые результаты для этого слова.
            self.errors.pop(
                word,
                None
            )

            pattern = re.compile(
                r'(?<![A-Za-zА-Яа-яЁё])'
                + re.escape(word)
                + r'(?![A-Za-zА-Яа-яЁё])',
                0
            )

            for filename in self.files:

                try:
                    text = filename.read_text(
                        encoding='utf-8'
                    )
                except Exception:
                    continue

                lines = text.splitlines()

                content_started = False

                for line_number, original_line in enumerate(
                    lines,
                    start=1
                ):

                    if not content_started:

                        if not original_line.strip():
                            content_started = True

                        continue

                    if re.search(
                        r'={2,}',
                        original_line
                    ):
                        continue

                    line = re.sub(
                        r'\[\[.*?\]\]',
                        ' ',
                        original_line
                    )

                    match = pattern.search(
                        line
                    )

                    if not match:
                        continue

                    if not self.dictionary.check(
                        word
                    ):

                        if word not in self.errors:
                            self.errors[word] = []

                        self.errors[word].append(
                            (
                                filename,
                                line_number,
                                original_line
                            )
                        )

            if word not in self.errors:

                self.current_word = None
                self.current_occurrence = 0

                self._rebuild_word_list()
                self._clear_context()

            else:

                self.current_occurrence = 0

                self._rebuild_word_list()
                self._show_current_occurrence()

        except Exception as error:

            self._show_background_error(
                'Не удалось перепроверить слово:\n{}'.format(
                    error
                )
            )

    # =====================================================
    # Recheck note
    # =====================================================

    def _recheck_note(self, button):

        if self.current_filename is None:
            return

        filename = self.current_filename

        try:
            if self.dictionary is None:
                self.dictionary = enchant.Dict(
                    'ru_RU'
                )

            # Удаляем старые ошибки этой заметки.
            for word in list(
                self.errors.keys()
            ):

                self.errors[word] = [
                    occurrence
                    for occurrence in self.errors[word]
                    if occurrence[0] != filename
                ]

                if not self.errors[word]:
                    del self.errors[word]

            # Заново проверяем только эту заметку.
            self._check_file(
                filename,
                self.dictionary,
            )

            # Ищем, осталось ли в текущей заметке
            # место текущего слова.
            occurrences = self.errors.get(
                self.current_word,
                []
            )

            note_occurrences = [
                occurrence
                for occurrence in occurrences
                if occurrence[0] == filename
            ]

            if not note_occurrences:

                self.current_word = None
                self.current_occurrence = 0

                self._rebuild_word_list()
                self._clear_context()

            else:

                self.current_occurrence = 0

                self._rebuild_word_list()
                self._show_current_occurrence()

        except Exception as error:

            self._show_background_error(
                'Не удалось перепроверить заметку:\n{}'.format(
                    error
                )
            )

    # =====================================================
    # Open current note
    # =====================================================

    def _open_current_note(self, button):

        if self.current_word is None:
            return

        occurrences = self.errors.get(
            self.current_word,
            []
        )

        if not occurrences:
            return

        filename, line_number, line = (
            occurrences[
                self.current_occurrence
            ]
        )

        self._open_note(
            filename,
        )

    # =====================================================
    # Open note
    # =====================================================

    def _open_note(self, filename):

        try:

            file = LocalFile(
                str(filename)
            )

            page_path, file_type = (
                self.window.notebook.layout.map_file(
                    file
                )
            )

            page = (
                self.window.notebook.get_page(
                    page_path
                )
            )

            self.window.open_page(
                page
            )

            word = self.current_word

            if word is None:
                return

            occurrences = self.errors.get(
                self.current_word,
                []
            )

            note_occurrence = 0

            for occurrence in occurrences[
                :self.current_occurrence
            ]:

                if occurrence[0] == filename:
                    note_occurrence += 1

            GLib.idle_add(
                self._select_opened_word,
                word,
                note_occurrence
            )

        except Exception as error:

            dialog = Gtk.MessageDialog(
                transient_for=self.check_window,
                flags=Gtk.DialogFlags.MODAL,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text='Не удалось открыть заметку'
            )

            dialog.format_secondary_text(
                str(error)
            )

            dialog.run()
            dialog.destroy()

    def _select_opened_word(
        self,
        word,
        note_occurrence
    ):

        try:

            textview = self.window.pageview.textview
            buffer = textview.get_buffer()

            pattern = re.compile(
                r'(?<![A-Za-zА-Яа-яЁё])'
                + re.escape(word)
                + r'(?![A-Za-zА-Яа-яЁё])',
                0
            )

            text = buffer.get_text(
                buffer.get_start_iter(),
                buffer.get_end_iter(),
                True
            )

            matches = list(
                pattern.finditer(text)
            )

            if not matches:
                return False

            index = min(
                note_occurrence,
                len(matches) - 1
            )

            match = matches[index]

            start_iter = (
                buffer.get_iter_at_offset(
                    match.start()
                )
            )

            end_iter = (
                buffer.get_iter_at_offset(
                    match.end()
                )
            )

            buffer.select_range(
                start_iter,
                end_iter
            )

            textview.scroll_to_iter(
                start_iter,
                0.2,
                True,
                0.5,
                0.5
            )

            textview.grab_focus()

            return False

        except Exception as e:

            import traceback
            traceback.print_exc()

        return False

    # =====================================================
    # Error
    # =====================================================

    def _show_background_error(
        self,
        message
    ):

        if self.check_window is None:
            return False

        dialog = Gtk.MessageDialog(
            transient_for=self.check_window,
            flags=Gtk.DialogFlags.MODAL,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text='Ошибка проверки'
        )

        dialog.format_secondary_text(
            message
        )

        dialog.run()
        dialog.destroy()

        return False

    # =====================================================
    # Window destroyed
    # =====================================================

    def _on_window_destroy(
        self,
        window
    ):

        if self.stop_event is not None:
            self.stop_event.set()

        self.check_window = None
