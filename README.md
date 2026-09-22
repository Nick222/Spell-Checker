# Spell Checker for Zim

A spell-checking plugin for **Zim Desktop Wiki**.

The plugin is designed primarily for working with large personal text corpora stored in Zim. It allows users to find words that are not recognized by the dictionary, inspect all occurrences, navigate to the corresponding place in a note, and choose a replacement either from the system dictionary or from the user's own text corpus.

The plugin is intended not only for one-time proofreading, but also for long-term work with a large and continuously growing collection of notes.

---

## Core Idea

A conventional spell checker answers the question:

> "Is this word present in the dictionary?"

For a personal text corpus, this is often not enough.

A user's own notes may contain:

* names and surnames;
* organization names;
* specialized terminology;
* user-defined terms;
* rarely used words;
* historical or professional vocabulary;
* words absent from the system dictionary;
* spelling variants specific to the user's corpus.

For this reason, the plugin uses **two independent sources of replacement suggestions**:

1. the system spell-checking dictionary;
2. the user's **personal text corpus**.

---

# What Is the "User Text Corpus"?

The corpus is the collection of the user's texts from which the plugin builds its own vocabulary of known words.

This is not necessarily a "dictionary of correct words" in the conventional sense.

The corpus may contain words that are absent from the system dictionary but occur regularly in the user's own notes.

For example, if a specialized term occurs many times in the user's notes, it can be useful as a source of suggestions when correcting a similarly spelled unknown word.

The plugin also takes word frequency in the corpus into account. A frequently occurring word may therefore receive priority over a rare alternative.

The corpus and the system dictionary serve different purposes:

**System dictionary:**

> Which spellings are recognized by a general-purpose dictionary?

**User corpus:**

> Which words are actually used in my own texts?

---

# Interface

The main checking window contains several interconnected areas.

## Error List

The upper part of the window contains a list of words found by the spell checker.

The number of occurrences is shown for each word.

For example:

```text
anthropov        3
evolutoinary     1
multi-webinar    4
```

The list contains **unique misspelled words**, rather than a separate entry for every occurrence.

When a word is selected, the plugin displays its first detected occurrence.

---

# Navigating Between Occurrences

The same misspelled word may occur many times throughout the corpus.

For example:

```text
multi-webinar — occurrence 3 of 8
```

This means that the third occurrence of the word out of eight is currently displayed.

Navigation buttons allow the user to move between occurrences:

* previous;
* next.

When moving between occurrences, the following are updated together:

* the current occurrence number;
* the file name;
* the text preview;
* the highlighted word in the preview;
* the replacement suggestions.

---

# Preview

The preview area shows several lines of text around the current occurrence.

The current line is marked with:

```text
>>>
```

For example:

```text
      12: In the previous paper...
>>>   13: Here we found a multi-webinar...
      14: After that...
```

The target word is highlighted in the current line.

The preview makes it possible to understand the context of an error without opening the note.

When navigating between occurrences, the preview is updated automatically.

---

# Opening the Note

The button for opening the note takes the user directly to the file containing the current occurrence.

The plugin attempts to select the **specific occurrence**, rather than merely opening the correct note.

If the same word occurs several times in the note, the corresponding occurrence is selected.

---

# Replacement Suggestions

Below the preview there are two lists of replacement suggestions:

```text
From your corpus:         From dictionary:
-------------------       -------------------
suggestion 1              suggestion 1
suggestion 2              suggestion 2
suggestion 3              suggestion 3
...
```

## From Your Corpus

The first list contains words found in the user's own text corpus.

Suggestions are selected according to their similarity to the misspelled word.

The frequency of a word in the corpus is also taken into account.

If different capitalization variants exist in the corpus, the plugin attempts to take the capitalization of the original word into account as well.

---

## From Dictionary

The second list contains suggestions provided by the installed spell-checking dictionary through **Enchant**.

Thus, the system dictionary and the personal corpus work in parallel and complement one another.

---

# How Replacement Works

Replacement deliberately consists of **two separate actions**.

### Step 1. Select a suggestion

The user clicks once on the desired word in either suggestion list:

```text
From dictionary:

multi-webinar
multi-webinars
```

The selected item becomes the pending replacement.

The misspelled word is **not replaced yet**.

### Step 2. Click "Replace"

After a suggestion has been selected, the button becomes available:

```text
[ Replace ]
```

Clicking the button replaces the current occurrence.

After a successful replacement, the interface displays:

```text
Replaced
```

The plugin then automatically:

1. removes the replaced occurrence from the current error list;
2. recalculates the number of remaining occurrences;
3. updates the list of misspelled words;
4. selects the next remaining occurrence;
5. updates the preview;
6. updates the replacement suggestions.

The user can therefore continue checking the next occurrence immediately.

---

# Why Replacement Requires a Separate Button

Selecting a suggestion and performing a replacement are deliberately separate actions.

A click on an item in the suggestion list means:

> "I select this suggestion."

The **Replace** button means:

> "Now actually change the text."

This makes the operation explicit and prevents accidental replacements caused by an unintended click.

---

# Working with Multiple Occurrences

The plugin works with individual occurrences, not only with unique words.

If a word occurs five times:

```text
word — occurrence 1 of 5
```

each occurrence can be inspected and handled separately.

For example:

```text
Before:

wrong-word     occurrence 1
wrong-word     occurrence 2
wrong-word     occurrence 3
```

After replacing the first occurrence:

```text
correct-word   replaced
wrong-word     occurrence 1
wrong-word     occurrence 2
```

The number of remaining occurrences is recalculated automatically.

---

# Rechecking

The plugin provides commands for rechecking:

* the current word;
* the current note.

This is useful after manual edits and after making several replacements.

Rechecking makes it possible to verify that a correction has actually removed the error and that no other problems remain.

---

# Ignoring a Word

A word can be removed from the current checking list without automatically adding it to the system dictionary.

This is useful when a word is acceptable in the current project or corpus, but the user does not want to modify the general-purpose spell-checking dictionary.

---

# "Fix" vs. "Ignore"

The plugin distinguishes between two fundamentally different actions.

### Fix

Modify the text by replacing one specific erroneous occurrence.

### Ignore

Remove the word from the current checking list without modifying the text.

Ignoring a word does not automatically add it to the system spell-checking dictionary.

---

# Working with the Corpus and Dictionary

One of the main purposes of the plugin is to use a personal text corpus not as a replacement for a spell-checking dictionary, but as an **additional source of linguistic information**.

This is especially useful for long-lived Zim notebooks in which texts accumulate over many years.

The user's corpus may contain terminology that is absent from standard dictionaries. It can therefore help identify plausible replacements even when the system spell checker does not know the desired word.

---

# Correction Workflow

The plugin does not attempt to automatically "fix everything".

The intended workflow is:

```text
Find a misspelled word
        ↓
Check the number of occurrences
        ↓
Inspect the context
        ↓
Compare corpus and dictionary suggestions
        ↓
Select a suggestion
        ↓
Click "Replace"
        ↓
Inspect the next result
```

The final decision therefore always remains with the user.

---

# Technical Foundation

The plugin is designed to work with:

* **Zim Desktop Wiki**
* **Zim 0.77.x**
* **Python**
* **GTK 3**
* **Enchant**

Suggestions from the personal corpus are generated using string similarity, while dictionary suggestions are obtained from Enchant.

The plugin works directly with Zim's text files and does not require a separate database to store corrections.

---

# What the Plugin Does Not Do

The plugin is not intended for:

* automatic mass replacement of an entire corpus;
* blindly accepting dictionary suggestions;
* automatically adding every unknown word to the system dictionary;
* replacing Zim as a text editor;
* storing its own vocabulary in a separate opaque database.

The core principle is:

> **The user sees the problem, understands the context, and explicitly confirms the change.**

---

# Installation

Copy the plugin directory into Zim's user plugin directory:

```text
~/.local/share/zim/plugins/
```

For example:

```text
~/.local/share/zim/plugins/spell_checker/
```

Restart Zim and enable the plugin through the plugin manager.

---

# Compatibility

The plugin has been developed and tested with:

```text
Zim 0.77.2
```

Primary development environment:

```text
Linux
Python 3
GTK 3
Enchant
```

---

# Project Status

The plugin is currently in working condition.

Implemented features include:

* spell checking;
* unique misspelled-word list;
* occurrence counts;
* navigation between occurrences;
* contextual preview;
* opening the corresponding note;
* selecting the correct occurrence in the note;
* suggestions from the system dictionary;
* suggestions from the user's own corpus;
* explicit selection of a replacement;
* explicit confirmation with the **Replace** button;
* replacement of an individual occurrence;
* automatic updating of the error list after replacement;
* rechecking a word and a note;
* ignoring a word without modifying the system dictionary.

---

# Project Concept

Spell checking here is treated as more than simply finding typos.

For a large personal archive of texts, the accumulated linguistic material itself is valuable: words, terms, and spelling variants that actually occur in the user's corpus.

The plugin therefore combines two sources:

```text
             ┌───────────────────┐
             │  Misspelled word  │
             └─────────┬─────────┘
                       │
              ┌────────┴────────┐
              │                 │
              ▼                 ▼
      ┌──────────────┐   ┌──────────────┐
      │ System       │   │ Personal     │
      │ dictionary   │   │ corpus       │
      │ (Enchant)    │   │              │
      └──────┬───────┘   └──────┬───────┘
             │                  │
             └────────┬─────────┘
                      ▼
              Replacement suggestions
                      │
                      ▼
               User selects one
                      │
                      ▼
                  Replace
```

This allows a personal text corpus accumulated over many years to serve as an additional source of language information while keeping the user fully in control of every change.

---

# License

Add the project license here after choosing a license for the repository.
