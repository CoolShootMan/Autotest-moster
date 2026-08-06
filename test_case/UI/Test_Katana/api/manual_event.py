import json, requests
v=json.load(open("prefill_vars.json",encoding="utf-8"))
tok=v.get("token","")
BASE="https://release.katana-api.1m.app"
hdr={"authorization":"Bearer "+tok,"content-type":"application/json","accept":"application/json"}

event_body={"ignoreStartTime":True,"ignoreEndTime":True,"isTimeUnspecified":False,"allowAutoComplete":True,"description":"","note":"linda note","location":"789 River East Art Center Promenade, Chicago, Illinois, USA","status":"UPCOMING","descriptionBodyJson":"{\"root\":{\"children\":[{\"children\":[],\"direction\":\"ltr\",\"format\":\"\",\"indent\":0,\"type\":\"katana-paragraph\",\"version\":1,\"textFormat\":0,\"textStyle\":\"\",\"style\":\"\"}],\"direction\":null,\"format\":\"\",\"indent\":0,\"type\":\"root\",\"version\":1}}","isTaxEnabled":False,"isAddressRevealEnabled":False,"title":"verify-co-seller-auto-archive","venue":"Instagram Live, Zoom, In-person","timezone":{"timeZoneId":"America/Chicago","timeZoneName":"Central Daylight Time","dstOffset":3600,"rawOffset":-21600},"poster":{"height":2048,"width":3072,"src":"https://res.cloudinary.com/dr9io1zjv/v1762842604/uploaded_images/s47jfs33fgz3do4wvrxz.png","mediaType":"IMAGE"},"startDateDisplay":"2053-04-17","styleSettings":{"fontFamily":"Inter","color":"#FFFFFF","backgroundColor":"#000000","borderColor":"#000000","dividerColor":"#FFFFFF","secondaryTextColor":"#E0E0E0","announcementCarousel":{"color":"#000000","backgroundColor":"#F6CA7C"},"title":{"color":"#F6CA7C","fontFamily":"Inter","fontSize":24,"fontWeight":700},"columnTitle":{"fontFamily":"Inter","fontSize":20,"fontWeight":700,"color":"#FFFFFF"},"subtitle":{"fontFamily":"Inter","fontSize":20,"fontWeight":400,"color":"#FFFFFF"}}}

r=requests.post(BASE+"/product-event", headers=hdr, json=event_body, timeout=30)
print("create event:", r.status_code)
eid=r.json().get("data",{}).get("id")
print("event_id:", eid)

media_body={"poster":{"src":"https://res.cloudinary.com/dr9io1zjv/v1762842604/uploaded_images/s47jfs33fgz3do4wvrxz.png","width":3072,"height":2048,"position":0,"mediaType":"IMAGE","mediaDuration":0},"posterBackend":[{"src":"https://res.cloudinary.com/dr9io1zjv/v1762842604/uploaded_images/s47jfs33fgz3do4wvrxz.png","width":3072,"height":2048,"position":0,"mediaType":"IMAGE","mediaDuration":0}],"medias":[],"mediaTextConfig":{"headline":"Missed our last event?","subtitle":"Here's a lil recap of our last event👇","align":"center"}}
r=requests.post(BASE+"/product-event/v2/%s/media/batch/create"%eid, headers=hdr, json=media_body, timeout=30)
print("media:", r.status_code, r.text[:120])

ticket_body={"poster":{"src":"https://res.cloudinary.com/dr9io1zjv/v1762842604/uploaded_images/s47jfs33fgz3do4wvrxz.png","width":3072,"height":2048,"position":0,"mediaType":"IMAGE","mediaDuration":0},"listingType":"TICKET","isTaxEnabled":False,"autoReplace":False,"tickets":[{"listingType":"TICKET","ticketType":"TICKET_TYPE_STANDARD","images":[{"id":"80f43627-4bef-49b0-934b-cd63d49f8787","height":1000,"width":1000,"src":"https://res.cloudinary.com/dr9io1zjv/v1755656006/uploaded_images/pt4zctae8zwv8jrljrf7.png","mediaType":"IMAGE"}],"title":"General Admission","bodyJson":"","options":[{"name":"Title","values":["Default Title"],"images":[]}],"variants":[{"inventoryQuantity":1000,"ticketPrice":22,"price":25.55,"fees":3.55,"priceAnchor":0,"option":{"option1":"Default Title"}}]}]}
r=requests.post(BASE+"/product-event/v2/%s/ticket/batch/v2"%eid, headers=hdr, json=ticket_body, timeout=30)
print("ticket:", r.status_code, r.text[:200])

r=requests.post(BASE+"/product-event/v2/%s/lineup/batch"%eid, headers=hdr, json={"lineup":[]}, timeout=30)
print("lineup:", r.status_code, r.text[:100])

r=requests.get(BASE+"/posts/curator/event/%s/posts"%eid, headers=hdr, timeout=30)
print("get posts:", r.status_code)
data=r.json()
print("items count:", len(data.get("data",{}).get("items",[])))
