from pathlib import Path
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

        self.current_filename = None

        self.dictionary = None

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
            1000,
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

            error_file = Path(
                'spell_checker_errors.txt'
            )

            with error_file.open(
                'w',
                encoding='utf-8'
            ) as output:

                output.write(
                    '# Spell Checker diagnostic output\n'
                )

                output.write(
                    '# Format: filename:line:word\n\n'
                )

                for filename in self.files:

                    if self.stop_event.is_set():
                        break

                    self._check_file(
                        filename,
                        self.dictionary,
                        output
                    )

                    self.checked += 1

                    GLib.idle_add(
                        self._update_progress,
                        self.checked,
                        total
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
        output
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

                if dictionary.check(word):
                    continue

                if output is not None:
                    output.write(
                        '{}:{}:{}\n'.format(
                            filename,
                            line_number,
                            word
                        )
                    )

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

        if word is None:
            return

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

                context.append(
                    '{}{:6}: {}'.format(
                        marker,
                        number,
                        all_lines[index]
                    )
                )

            text = (
                str(filename)
                + '\n\n'
                + '\n'.join(context)
            )

        except Exception:
            text = (
                '{}:{}\n\n{}'.format(
                    filename,
                    line_number,
                    line
                )
            )

            buffer = self.context_view.get_buffer()
            buffer.set_text(text)

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

        pattern = re.compile(
            r'(?<![A-Za-zА-Яа-яЁё])'
            + re.escape(word)
            + r'(?![A-Za-zА-Яа-яЁё])',
            re.IGNORECASE
        )

        match = pattern.search(
            selected_context_line
        )

        if match:
            line_start = len(
                str(filename)
            ) + 2

            if selected_context_index > 0:
                line_start += len(
                    '\n'.join(
                        context[
                            :selected_context_index
                        ]
                    )
                ) + 1

            word_start = (
                line_start
                + match.start()
            )

            word_end = (
                line_start
                + match.end()
            )

            start_iter = (
                buffer.get_iter_at_offset(
                    word_start
                )
            )

            end_iter = (
                buffer.get_iter_at_offset(
                    word_end
                )
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
        self.updating_model = True

        self.model.clear()

        words = sorted(self.errors.keys(), key=lambda word: word.lower())
        for word in words:
            self.model.append([word, len(self.errors[word])])

        self.updating_model = False

        self.status_label.set_text(
            'Осталось уникальных слов: {}'.format(len(self.errors))
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
                re.IGNORECASE
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
                None
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

            self.window.pageview.set_page(
                page
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
