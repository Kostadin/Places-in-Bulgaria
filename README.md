# Населени места в България, пощенски кодове, ЕКАТТЕ кодове, телефонни кодове, GPS координати, области, общини и кметства

Информацията тук е публична, безплатна и свободна за разпространение.

Places-in-Bulgaria.json
-----------------------
Структура на файла:
```javascript
{
  "Име на област": {
    "Име на община": {
      "ЕКАТТЕ код": {
      	"name": "Име на населеното място",
        "type": "Тип на населеното място (гр./с./ман./к.к.)",
        "town_hall": "Кметство",
        "phone_code": "Стационарен телефонен код",
        "latitutude": 12.345678, // GPS ширина
        "longitude": 23.456789, // GPS дължина
        "post_codes": [
        	"4000",
            "4001",
            "4002",
            "4003",
            "4004",
            "4030", ... // Пощенски кодове
        ]
      }, ...
    }, ...
  }, ...
}
```

Пример за 1 област, 1 община, 1 населено място:
```javascript
{
  "Пловдив": {
	"Пловдив": {
      "56784": {
        "name": "Пловдив",
        "type": "гр.",
        "town_hall": "Пловдив",
        "phone_code": "032",
        "latitude": 42.1354,
        "longitude": 24.7453,
        "post_codes": [
          "4000",
          "4001",
          "4002",
          "4003",
          "4004",
          "4006",
          "4008",
          "4013",
          "4015",
          "4016",
          "4017",
          "4018",
          "4019",
          "4020",
          "4021",
          "4023",
          "4024",
          "4027",
          "4030"
        ]
      }
    }
  }
}
```

Типове населени места:
  * "с." - село
  * "гр." - град
  * "ман." - манастир
  * "к.к." - курортен комплекс



Някои уточнения: "София" и "София област" са две различни области. Градът София и близките до него градове и села се намират в област "София". Област "София област" граничи с област "София", но е отделна административна единица. Повече информация (тук)[https://bg.wikipedia.org/wiki/%D0%A1%D0%BE%D1%84%D0%B8%D1%8F#%D0%9D%D1%8F%D0%BA%D0%BE%D0%B8_%D1%83%D1%82%D0%BE%D1%87%D0%BD%D0%B5%D0%BD%D0%B8%D1%8F_%D0%B8_%D0%B7%D0%B0%D0%B1%D0%B5%D0%BB%D0%B5%D0%B6%D0%BA%D0%B8].

Източниците на информация са няколко уебсайта със свободна публична информация:

[https://pnb.pc-remonti.net/ekatte]
[https://www.bgpost.bg/bg/17]
[https://crc.bg/files/_bg/post_codes_all__4_-_2016full.pdf]
[https://www.nsi.bg/nrnm/]
[https://kais.cadastre.bg/bg/Map]

Информацията беше първоначално сглобена от (Линкър Геймс ЕООД)[https://www.linkergames.com/] и е безплатна и свободна за използване и разпространение.

Ако намерите грешки, неточности или липсваща информация, моля, помогнете за общото благо като съобщите за това (тук)[https://github.com/Kostadin/Places-in-Bulgaria/issues] или качете Pull Request (тук)[https://github.com/Kostadin/Places-in-Bulgaria/pulls]. При Ваше желание, ще получите признание за приноса Ви на текущата страница.

Ако имате нужда от подробна информация за границите на всяко отделно населено място, препоръчваме следния източник на информация:
[https://github.com/yurukov/Bulgaria-geocoding]
