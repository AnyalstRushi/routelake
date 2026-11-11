.PHONY: test demo check clean

test:
	python3 -W error -m unittest discover -s tests -v

demo:
	python3 -m routelake demo

check: test
	python3 -m compileall -q routelake tests
	python3 -m routelake demo > /dev/null
	@git diff --exit-code reports data/sample > /dev/null 2>&1 || echo "note: demo outputs differ from committed copies"

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
