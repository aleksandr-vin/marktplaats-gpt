from bs4 import BeautifulSoup
import requests
import logging
import json

def load_item_data(item_id):
    """
    Loads marktplaats item data by scraping the html page.
    """

    response = requests.get(f'https://www.marktplaats.nl/{item_id}')

    response.raise_for_status()
    with open(f'cache/{item_id}.html', 'w') as file:
        file.write(response.text)
    logging.debug('reply saved to %s', file.name)

    soup = BeautifulSoup(response.text, "html.parser")

    for e in soup.find_all(type="application/ld+json"):
        try:
            j = json.loads(e.text)
            if j['@type'] == 'Product':
                product = {
                    "name": j['name'],
                    "description": j['description'],
                    "price": j['offers']['price'],
                    "priceCurrency": j['offers']['priceCurrency'],
                }
                logging.info("Item %s data: %s", item_id, product)
                return json.dumps(product)
        except e:
            logging.error(e)

    logging.warn("No product information found")
    return None