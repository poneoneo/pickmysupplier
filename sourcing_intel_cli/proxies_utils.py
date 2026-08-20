HTML_PAGE_RESULT = []


def urls_pusher(words: str, stop_at: int):
	for i in range(1, stop_at + 1):
		yield f"https://www.alibaba.com/trade/search?spm=a2700.galleryofferlist.0.0.64271d1dZRDxt1&fsb=y&IndexArea=product_en&keywords={words}&tab=all&&page={i}"
