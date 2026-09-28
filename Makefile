.PHONY: test run check demo

test:
	python3 -m unittest discover -s tests -v

run:
	python3 -m sarview

check:
	python3 -m sarview --check

demo:
	python3 -m sarview --demo
