// Функція для налаштування вебхука
function setWebhook() {
  const scriptUrl = ScriptApp.getService().getUrl();
  const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook?url=${scriptUrl}`;

  try {
    const response = UrlFetchApp.fetch(url);
    Logger.log(response.getContentText());
  } catch (e) {
    if (e.message.includes('429')) {
      Logger.log('Too many requests. Retrying after 1 second...'); 
      Utilities.sleep(1000);  // тут іде затримка аби не валилась помилка
      setWebhook(); 
    } else {
      Logger.log('Error setting webhook: ' + e.message);
    }
  }
}

// Функція для обробки нових повідомлень
function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    const message = data.message.text;
    const userId = data.message.chat.id;
    const chatType = data.message.chat.type;

    Logger.log(`Received message: ${message}`);
    Logger.log(`Chat type: ${chatType}`);

    // Перевірка, чи повідомлення є приватним або починається з команди
    if (chatType !== 'private' && !message.startsWith('/')) {
      Logger.log('Message is not private and does not start with a command. Ignoring.');
      return;
    }

    const userProperties = PropertiesService.getUserProperties();
    let currentChatId = userProperties.getProperty('currentChatId');
    let currentFormId = userProperties.getProperty('currentFormId');
    let bindings = userProperties.getProperty('bindings') ? JSON.parse(userProperties.getProperty('bindings')) : [];

    Logger.log(`Current chatId: ${currentChatId}`);
    Logger.log(`Current formId: ${currentFormId}`);
    Logger.log(`Bindings: ${JSON.stringify(bindings)}`);

    if (message.startsWith('/start')) {
      sendMessage(userId, 'Вітаю! Ось список команд:\n/connect - Прив\'язати чат до форми\n/reset - Видалити дані\n/delete - Видалити конкретний чат\n/list - Переглянути всі форми');

    } else if (message.startsWith('/reset')) {
      userProperties.deleteProperty('currentChatId');
      userProperties.deleteProperty('currentFormId');
      userProperties.deleteProperty('bindings');
      sendMessage(userId, 'Дані успішно видалені)');

    } else if (message.startsWith('/delete')) {
      sendMessage(userId, 'Введіть chatId, який потрібно видалити, у форматі -**********:');
      userProperties.setProperty('deleteMode', 'true');

    } else if (message.startsWith('/connect')) {
      sendMessage(userId, 'Введіть ваш chatId у форматі -**********:');
      userProperties.deleteProperty('currentChatId');
      userProperties.deleteProperty('currentFormId');

    } else if (message.startsWith('/list')) {
      listBindings(userId);

    } else if (userProperties.getProperty('deleteMode') === 'true') {
      deleteChat(message);
      userProperties.deleteProperty('deleteMode');

    } else if (!currentChatId) {
      currentChatId = message;
      checkChatMember(userId, currentChatId);

    } else if (!currentFormId) {
      currentFormId = message;

      if (validateFormId(currentFormId)) {
        bindings.push({ chatId: currentChatId, formId: currentFormId });
        userProperties.setProperty('bindings', JSON.stringify(bindings));
        userProperties.deleteProperty('currentChatId');
        userProperties.deleteProperty('currentFormId');
        sendMessage(userId, 'Дякую! Бот налаштований.');
        setupTriggers();
        sendMessage(currentChatId, 'Бот успішно налаштований! Тепер у чат надходитимуть відповіді з форми.');
      } else {
        sendMessage(userId, 'Помилка: Неправильний formId. Будь ласка, введіть правильний formId:');
      }
    }
  } catch (error) {
    Logger.log('Error in doPost: ' + error.message);
  }
}

// Функція, котра перевіряє чи є користувач членом чату
function checkChatMember(userId, chatId) {
  const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getChatMember?chat_id=${chatId}&user_id=${userId}`;

  try {
    const response = UrlFetchApp.fetch(url);
    const result = JSON.parse(response.getContentText());

    if (result.ok && result.result.status !== 'left' && result.result.status !== 'kicked') {
      PropertiesService.getUserProperties().setProperty('currentChatId', chatId);
      sendMessage(userId, 'Дякую! Тепер введіть ваш formId. \nFormId знаходить у посилання, як показано нижче\n https://docs.google.com/forms/d/FormId/edit:');
    } else {
      Logger.log('User is not a member of the chat or has left/kicked: ' + JSON.stringify(result)); 
      sendMessage(userId, 'Помилка: Ви не є членом цього чату. Будь ласка, введіть правильний chatId.');
    }
  } catch (e) {
    Logger.log('Error checking chat member: ' + e.message);
    sendMessage(userId, 'Помилка: Не вдалося перевірити chatId. Будь ласка, введіть правильний chatId.');
  }
}

// Функція для перевірки правильності formId
function validateFormId(formId) {
  try {
    FormApp.openById(formId);
    return true;
  } catch (e) {
    Logger.log('Invalid formId: ' + formId);
    return false;
  }
}

// Функція для надсилання повідомлень
function sendMessage(chatId, text) {
  if (!chatId) {
    Logger.log('chatId is empty');
    return;
  }

  const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`;
  const payload = {
    chat_id: chatId,
    text: text,
    parse_mode: 'HTML'
  };

  const options = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
  };

  const response = UrlFetchApp.fetch(url, options);
  Logger.log(response.getContentText());
}

// Функція для надсилання фотографій
 function sendPhoto(chatId, photoUrl) {
   if (!chatId) {
     Logger.log('chatId is empty');
     return;
   }

   const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendPhoto`;
   const payload = {
     chat_id: chatId,
     photo: photoUrl
   };

   const options = {
     method: 'post',
     contentType: 'application/json',
     payload: JSON.stringify(payload),
   };

   const response = UrlFetchApp.fetch(url, options);
   Logger.log(response.getContentText());
 }

// Функція для обробки подій форми
function onFormSubmit(e) {
  const formResponses = e.response.getItemResponses();
  const formId = e.source.getId();

  let message = '<b>Нова заповнена форма</b>\n\n';
  let photos = [];

  formResponses.forEach(response => {
    const question = response.getItem().getTitle();
    const answer = response.getResponse();

    if (response.getItem().getType() === FormApp.ItemType.FILE_UPLOAD) {
      const fileIds = answer; // отримуємо ідентифікатори файлів
      fileIds.forEach(fileId => {
        const file = DriveApp.getFileById(fileId);
        file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW); // робимо файл загальнодоступним
        const fileUrl = file.getUrl();
        photos.push(fileUrl);
      });
    } else {
      message += `<b>${question}:</b> ${answer}\n`;
    }
  });

  const userProperties = PropertiesService.getUserProperties();
  const bindings = userProperties.getProperty('bindings') ? JSON.parse(userProperties.getProperty('bindings')) : [];
  const binding = bindings.find(b => b.formId === formId);

  if (!binding) {
    Logger.log('No binding found for formId: ' + formId);
    return;
  }

  const chatId = binding.chatId;

  if (!chatId) {
    Logger.log('chatId is empty');
    return;
  }

  // Надсилання текстового повідомлення
  sendMessage(chatId, message);
}

// Функція для налаштування тригерів
function setupTriggers() {
  const triggers = ScriptApp.getProjectTriggers();
  triggers.forEach(trigger => {
    if (trigger.getHandlerFunction() === 'onFormSubmit') {
      ScriptApp.deleteTrigger(trigger);
    }
  });

  const userProperties = PropertiesService.getUserProperties();
  const bindings = userProperties.getProperty('bindings') ? JSON.parse(userProperties.getProperty('bindings')) : [];

  Logger.log(`Setting up triggers with bindings: ${JSON.stringify(bindings)}`);

  bindings.forEach(binding => {
    const formId = binding.formId;
    const chatId = binding.chatId;

    if (formId) {
     try {
        const form = FormApp.openById(formId);
        const existingTriggers = ScriptApp.getUserTriggers(form).filter(trigger => trigger.getHandlerFunction() === 'onFormSubmit');
        if (existingTriggers.length === 0) {
          ScriptApp.newTrigger('onFormSubmit')
                   .forForm(form)
                   .onFormSubmit()
                   .create();
        }
        Logger.log('Invalid formId: ' + formId);
      } catch (e) {
        sendMessage(chatId, 'Помилка: Неправильний formId. Будь ласка, введіть правильний formId:');
        bindings.pop(); // Видаляється неправильний formId
         userProperties.setProperty('bindings', JSON.stringify(bindings));
      }
    } else {
      Logger.log('formId is empty');
      sendMessage(chatId, 'Помилка: formId не може бути порожнім. Будь ласка, введіть formId.');
    }
  });
}

// Функція для видалення чату
function deleteChat(chatId) {
  const userProperties = PropertiesService.getUserProperties();
  let bindings = userProperties.getProperty('bindings') ? JSON.parse(userProperties.getProperty('bindings')) : [];

  bindings = bindings.filter(binding => binding.chatId !== chatId); // тут видаляються усі форми, котрі прив'язані до чату
                                                                    // потім можна буде налаштувати ще видалення за формою
  userProperties.setProperty('bindings', JSON.stringify(bindings));
  sendMessage(chatId, 'Чат та форми успішно видалені.'); 
}

// Функція для перегляду всіх прив'язок. Перевіряє конект чату до форм через властивсті користувача.
// Або як варіант реалізації потім: то перевіряти усі прив'язки за окремим чатами, 
// хоча ця функція і так виносить список усіх чаті та форм
function listBindings(userId) {
  const userProperties = PropertiesService.getUserProperties();
  const bindings = userProperties.getProperty('bindings') ? JSON.parse(userProperties.getProperty('bindings')) : [];

  if (bindings.length > 0) {
    let message = 'Прив’язані чати та форми:\n';
    bindings.forEach((binding, index) => {
      message += `${index + 1}. ChatId: ${binding.chatId}, FormId: ${binding.formId}\n`;
    });
    sendMessage(userId, message);
  } else {
    sendMessage(userId, 'Немає прив’язаних чатів та форм.');
  }
}

setWebhook();