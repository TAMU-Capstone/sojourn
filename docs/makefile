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
BROWSER := $(firstword $(wildcard \
  /Applications/Chromium.app/Contents/MacOS/Chromium \
  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  /Applications/Microsoft\ Edge.app/Contents/MacOS/Microsoft\ Edge \
  /opt/pw-browsers/chromium) \
  $(shell command -v chromium chromium-browser google-chrome 2>/dev/null))

.PHONY: all docx register manual deck check deps clean
all: register docx manual

# ---- Word exports -------------------------------------------------------
docx: $(DOCXS)

%.docx: %.md build_docx.js
	@command -v $(NODE) >/dev/null || { \
	  echo "SKIP $@ — node is not installed (brew install node)"; exit 0; }
	@test -d node_modules || { \
	  echo "SKIP $@ — run 'make deps' first"; exit 0; }
	@$(NODE) build_docx.js $< $@

# requirements.md is generated, so its export depends on the register
requirements.docx: register

# ---- the requirements register ------------------------------------------
# Generated from charter.md: every requirement has exactly one identifier and
# it is defined there. Never edit requirements.md by hand.
register:
	@$(PYTHON) $(TOOLS)/requirements.py --write

# ---- the player-facing manual -------------------------------------------
# Chromium prints dbus warnings and can exit non-zero even on success, so
# judge it by whether the PDF actually appeared rather than by its status.
manual: manual.html
	@if [ -z "$(BROWSER)" ]; then \
	  echo "SKIP manual.pdf — no chromium/chrome found; manual.html is built"; \
	else \
	  rm -f $(DOCS)manual.pdf; \
	  "$(BROWSER)" --headless --disable-gpu --no-sandbox --no-pdf-header-footer \
	    --print-to-pdf=$(DOCS)manual.pdf $(DOCS)manual.html >/dev/null 2>&1 || true; \
	  if [ -s $(DOCS)manual.pdf ]; then echo "wrote manual.pdf"; \
	  else echo "FAILED to write manual.pdf; manual.html is built"; exit 1; fi; \
	fi

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
