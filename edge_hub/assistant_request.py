from edge_hub.event_request import EventBodyLimitMiddleware


class AssistantBodyLimitMiddleware(EventBodyLimitMiddleware):
    label = 'assistant'

    def matches(self, scope):
        return (scope['type'] == 'http' and scope.get('method') in {'POST', 'PUT', 'PATCH', 'DELETE'}
                and (scope.get('path', '').startswith('/api/v1/assistant/')
                     or scope.get('path', '').rstrip('/') == '/v1/chat/completions'))
