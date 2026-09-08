# makefile — build the Sojourn documents.
#
# Sources are the markdown files in this directory; everything else here is
# generated from them and should not be hand-edited. Edit the .md, run make.
#
#   make            everything below that your machine can build
#   make docx       the Word exports, one per specification
#   make register   requirements.md and requirements.csv, from charter.md
#   make manual     the player-facing manual as HTML, and PDF if possible
#   make deck       the capstone pitch deck
#   make check      requirement identifiers resolve; report what is installed
#   make deps       npm install (needed once, for the Word exports)
#   make clean      remove generated files
#
# Dependencies, and what you lose without each:
#   python3   required for everything
#   node+npm  the .docx exports        (brew install node)
#   chromium  the manual PDF only      (brew install --cask chromium)
#             any of chromium, chrome or Edge is fine; HTML builds regardless

PYTHON  ?= python3
NODE    ?= node
DOCS    := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
TOOLS   := $(DOCS)../firmware/tools

# Every specification that gets a Word export. manual.md is excluded: it is
# player-facing fiction and ships as a styled PDF instead.
SPECS := charter firmware_spec introspection_api platform_design \
         requirements scenario_authoring scenario_format
DOCXS := $(addsuffix .docx,$(SPECS))

# A headless browser, if one is installed. Used only for the manual PDF.
# Found with a shell loop rather than $(wildcard) + $(firstword). The Chrome
# and Edge paths contain a space, and make's word functions split on
# whitespace, so firstword silently truncated the browser to
# "/Applications/Google" and every PDF build failed with "No such file".
BROWSER := $(shell for b in \
    /Applications/Chromium.app/Contents/MacOS/Chromium \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    /opt/pw-browsers/chromium \
    "`command -v chromium 2>/dev/null`" \
    "`command -v chromium-browser 2>/dev/null`" \
    "`command -v google-chrome 2>/dev/null`" ; do \
      [ -n "$$b" ] && [ -x "$$b" ] && printf '%s' "$$b" && break ; \
    done)

.PHONY: all docx register manual deck check deps clean
all: requirements.md docx manual

# ---- Word exports -------------------------------------------------------
docx: $(DOCXS)

%.docx: %.md build_docx.js
	@command -v $(NODE) >/dev/null || { \
	  echo "SKIP $@ — node is not installed (brew install node)"; exit 0; }
	@test -d node_modules || { \
	  echo "SKIP $@ — run 'make deps' first"; exit 0; }
	@$(NODE) build_docx.js $< $@

# requirements.docx follows requirements.md like every other export; the
# dependency below is what regenerates requirements.md when the charter moves.

# ---- the requirements register ------------------------------------------
# Generated from charter.md: every requirement has exactly one identifier and
# it is defined there. Never edit requirements.md by hand.
# Generated from charter.md, so it is rebuilt when charter.md is newer. It
# used to hang off the phony `register` target, which made it unconditionally
# out of date: every `make docx` rewrote requirements.docx, and because a .docx
# embeds a build timestamp the bytes changed each time, so git reported the
# file modified for ever. This rule rebuilds it when, and only when, the
# charter has actually changed.
requirements.md: charter.md $(TOOLS)/requirements.py
	@$(PYTHON) $(TOOLS)/requirements.py --write

requirements.csv: requirements.md

# Force it, whatever the timestamps say.
register:
	@$(PYTHON) $(TOOLS)/requirements.py --write

# ---- the player-facing manual -------------------------------------------
# The PDF step lives in build_pdf.sh because it needs a hard timeout, a
# private browser profile and a build-then-move: too much for a recipe line.
# A missing PDF is a skip, never a build failure. The HTML is the deliverable.
manual: manual.html
	@sh $(DOCS)build_pdf.sh $(DOCS)manual.html $(DOCS)manual.pdf

manual.html: manual.md build_manual.py
	@$(PYTHON) build_manual.py $< $@

# ---- the pitch deck -----------------------------------------------------
deck:
	@command -v $(NODE) >/dev/null && test -d node_modules \
	  && $(NODE) build_deck.js capstone_pitch.pptx \
	  || echo "SKIP deck — needs node and 'make deps'"

# ---- checks -------------------------------------------------------------
check:
	@$(PYTHON) $(TOOLS)/requirements.py --check
	@echo "toolchain:"
	@printf "  %-10s " python3; command -v $(PYTHON) >/dev/null && $(PYTHON) --version || echo "MISSING (required)"
	@printf "  %-10s " node;    command -v $(NODE)   >/dev/null && $(NODE) --version   || echo "missing (no .docx exports)"
	@printf "  %-10s " deps;    test -d node_modules && echo "installed" || echo "not installed — run 'make deps'"
	@printf "  %-10s " browser; test -n "$(BROWSER)" && echo "$(BROWSER)" || echo "missing (no manual.pdf)"

deps:
	@npm install

clean:
	@rm -f $(DOCXS) manual.html
	@echo "removed the Word exports and manual.html"
	@echo "kept: manual.pdf, capstone_pitch.pptx (rebuild with 'make manual' / 'make deck')"
