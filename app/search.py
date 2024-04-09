from flask import current_app


def add_to_index(index, model):
    if not current_app.elasticsearch:
        return
    payload = {}
    for field in model.__searchable__:
        payload[field] = getattr(model, field)
    current_app.elasticsearch.index(index=index, id=model.id, body=payload)


def remove_from_index(index, model):
    if not current_app.elasticsearch:
        return
    current_app.elasticsearch.delete(index=index, id=model.id)


def query_index(index, query, page, per_page):
    if not current_app.elasticsearch:
        return [], 0
    search = current_app.elasticsearch.search(
        index=index,
        body={'query': {'multi_match': {'query': query, 'fields': ['*']}},
              'from': (page - 1) * per_page, 'size': per_page})
    ids = [int(hit['_id']) for hit in search['hits']['hits']]
    return ids, search['hits']['total']['value']

    # ids: danh sach cac phan tu. search[][][]: tong ket qua

# ELASTIC SEARCH là công cụ tìm kiếm, có thể đc xem như 1 document oriented database
# Nó như 1 bản copy của database và việc tìm kiếm sẽ đc thực hiện trên đó

# Thay vì tìm kiếm trên database gốc thì chuyển data dó sang Elastic search và tìm kiếm trên đó.