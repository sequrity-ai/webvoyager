# Run all tasks
run QUERY URL ITER:
    uv run --env-file .env.localhost python sequrity_cua.py --task "{{QUERY}}" --url {{URL}} --max_iterations {{ITER}}

# Apple task
apple:
    uv run --env-file .env.localhost python sequrity_cua.py --task "Check the available colors for an Apple iPhone 17 Pro." --url "https://www.apple.com/" --max_iterations 20

# Allrecipes task
allrecipes:
    uv run --env-file .env.localhost python sequrity_cua.py --task "Provide a recipe for vegetarian lasagna with more than 100 reviews and a rating of at least 4.5 stars suitable for 6 people." --url "https://www.allrecipes.com/" --max_iterations 20

# Amazon task
amazon:
    uv run --env-file .env.localhost python sequrity_cua.py --task "Search an Xbox Wireless controller with green color and rated above 3 stars." --url "https://www.amazon.com/" --max_iterations 20

# ArXiv task
arxiv:
    uv run --env-file .env.localhost python sequrity_cua.py --task "Search for the latest preprints about 'quantum computing'." --url "https://arxiv.org/" --max_iterations 20

# BBC News task
bbc-news:
    uv run --env-file .env.localhost python sequrity_cua.py --task "Find a report on the BBC News website about recent developments in renewable energy technologies in the UK." --url "https://www.bbc.com/news/" --max_iterations 20

# Booking task
booking:
    uv run --env-file .env.localhost python sequrity_cua.py --task "Find the cheapest available hotel room for a three night stay from 1st Jan in Jakarta. The room is for 2 adults, just answer the cheapest hotel room and the price." --url "https://www.booking.com/" --max_iterations 20

# GitHub task
github:
    uv run --env-file .env.localhost python sequrity_cua.py --task "Look for the trending Python repositories on GitHub with most stars." --url "https://github.com/" --max_iterations 20
