# promptconf theory documentation
#
# Build:  make
# Clean:  make clean
# Requires: pdflatex (TeX Live / MacTeX)

TEX  = theory.tex
PDF  = theory.pdf
LATEX = pdflatex
LATEXFLAGS = -interaction=nonstopmode -halt-on-error

.PHONY: all clean

all: $(PDF)

$(PDF): $(TEX)
	$(LATEX) $(LATEXFLAGS) $(TEX)
	$(LATEX) $(LATEXFLAGS) $(TEX)

clean:
	rm -f *.aux *.log *.out *.toc *.pdf
