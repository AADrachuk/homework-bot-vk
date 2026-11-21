import os
import time
import sys
import random
import requests  # type: ignore
import logging
import vk_api  # type: ignore
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv  # type: ignore

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
VK_TOKEN = os.getenv('VK_TOKEN')
VK_USER_ID = os.getenv('VK_USER_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

# указываем настройки логгера для текущего файла
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# указываем обработчик логов
handler = RotatingFileHandler('homework.log', maxBytes=50000000, backupCount=5)
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s, '
    '%(levelname)s, '
    '%(message)s, '
    '%(name)s'
)
handler.setFormatter(formatter)

if not logger.handlers:
    logger.addHandler(handler)


def check_tokens():
    """Проверяет доступность переменных окружения."""
    if not PRACTICUM_TOKEN:
        logger.critical('Отсутствует переменная окружения PRACTICUM_TOKEN')
    if not VK_TOKEN:
        logger.critical('Отсутствует переменная окружения VK_TOKEN')
    if not VK_USER_ID:
        logger.critical('Отсутствует переменная окружения VK_USER_ID')
    return all([PRACTICUM_TOKEN, VK_TOKEN, VK_USER_ID])


def send_message(vk, message):
    """Отправляет сообщение пользователю в VK."""
    try:
        vk.messages.send(
            user_id=VK_USER_ID,
            message=message,
            random_id=random.randint(0, 2**31 - 1),
        )
        logger.debug('Сообщение отправлено: %s', message)
    except Exception as error:
        logger.exception('Ошибка при отправке сообщения: %s', error)
        raise


def get_api_answer(timestamp):
    """Делает запрос к API Практикума и возвращает ответ в виде словаря."""
    payload = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=payload)
    except requests.exceptions.RequestException as error:
        raise ConnectionError(f'Не удалось подключиться к API: {error}')

    if response.status_code != 200:
        raise RuntimeError(
            f'API вернул некорректный статус-код: {response.status_code}. '
            f'Ответ: {response.text}'
        )

    try:
        return response.json()
    except ValueError:
        raise RuntimeError('Ответ API не удалось привести к формату JSON')


def check_response(response):
    """Проверяет ответ API и возвращает список домашних работ."""
    if not isinstance(response, dict):
        raise TypeError('Ответ API должен быть словарем')

    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ "homeworks"')

    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError('Ключ "homeworks" должен быть списком')

    logger.debug(
        'Ответ API успешно проверен. Получено работ: %d',
        len(homeworks)
    )
    return homeworks


def parse_status(homework):
    """Извлекает статус работы и возвращает текст сообщения."""
    if 'homework_name' not in homework:
        raise KeyError('В ответе API нет ключа "homework_name"')

    if 'status' not in homework:
        raise KeyError('В ответе API нет ключа "status"')

    homework_name = homework['homework_name']
    status = homework['status']

    if status not in HOMEWORK_VERDICTS:
        raise ValueError(f'Неизвестный статус работы: {status}')

    verdict = HOMEWORK_VERDICTS[status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
    if not check_tokens():
        sys.exit(1)

    # Создаем сессию для бота
    vk_session = vk_api.VkApi(token=VK_TOKEN)
    vk = vk_session.get_api()
    timestamp = int(time.time())

    while True:
        try:
            # запрос к API
            response = get_api_answer(timestamp)
            # проверка ответа
            homeworks = check_response(response)

            timestamp = response.get('current_date', timestamp)

            # если есть обновления, то получить статус и отправить сообщение
            if homeworks:
                for homework in homeworks:
                    message = parse_status(homework)
                    send_message(vk, message)
            else:
                logger.debug('Новых статусов в ответе API нет.')

        except Exception as error:
            # логируем сбой
            message = f'Сбой в работе программы: {error}'
            logger.error(message, exc_info=True)
            try:
                send_message(vk, message)
            except Exception as send_error:
                logger.exception(
                    'Не удалось отправить уведомление об ошибке: %s',
                    send_error
                )
        # подожать некоторое время и вернуться в начало цикла
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
