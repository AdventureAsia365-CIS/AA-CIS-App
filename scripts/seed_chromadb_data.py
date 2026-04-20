"""
scripts/seed_chromadb_data.py
Auto-generated from CIS_Golden_Tours_20_v1.xlsx — 20 golden tours
Run: python scripts/seed_chromadb_data.py
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared.rag import GoldenTourRepository

GOLDEN_TOURS = [
  {
    "id": "GT-TH-001",
    "tenant_id": "aa-internal",
    "country": "Thailand",
    "src_name": "Northern Highlands Traverse",
    "aa_name": "Northern Highlands Traverse",
    "aa_summary": "A sustained traverse through northern Thailand's highlands, moving from the city edge of Chiang Mai into the quieter ridgelines above Doi Mae Salong, where Yunnanese tea culture and Akha hill tribe settlements coexist in terraced silence. The route continues west toward Mae Hong Son, passing through forest corridors that see few visitors outside the dry season. Each night is spent in a lodge or private homestay selected for position rather than profile.",
    "aa_highlights": [
      "Guided ridge walk above Doi Mae Salong through terraced Oolong gardens in early morning mist",
      "Three-day crossing of the Pai River valley into Mae Hong Son province on seldom-used forest trails",
      "Evening with a Lisu weaver in Ban Rak Thai, documented on film by the guide",
      "Full-day kayak section on the Mae Kok River between Tha Ton and Chiang Rai, passing four hilltribe settlements",
      "Small-group cooking session using foraged herbs with a Karen community kitchen in Mae La Noi"
    ],
    "quality_score": 7.5,
    "trip_type": "trekking"
  },
  {
    "id": "GT-TH-002",
    "tenant_id": "aa-internal",
    "country": "Thailand",
    "src_name": "Mekong River Slow Journey",
    "aa_name": "Mekong River Slow Journey",
    "aa_summary": "An unhurried passage along the upper Mekong corridor from Chiang Rai to the confluence at the Golden Triangle, travelling by longtail boat, slow local ferry, and on foot between riverside settlements. The journey is structured around the river's rhythm rather than a fixed daily distance, with time built in for market mornings, monastery visits, and unscheduled stops at fishing communities where the guide has existing relationships.",
    "aa_highlights": [
      "Full-day longtail passage from Chiang Khong to Sob Ruak along the Thai-Lao border, reading the river's seasonal character with the guide",
      "Dawn walk through Chiang Saen's walled city ruins before tourist arrivals, with a private briefing on Lanna-era cartography",
      "Afternoon with an opium-history specialist at the Hall of Opium, framed around the region's agricultural transition",
      "Evening meal at a riverside guesthouse in Chiang Khong, sourced from the family's own garden and the morning market",
      "Small-boat passage to the Laos border at Huay Xai, returning across the Mekong at dusk"
    ],
    "quality_score": 7.0,
    "trip_type": "river_journey"
  },
  {
    "id": "GT-TH-003",
    "tenant_id": "aa-internal",
    "country": "Thailand",
    "src_name": "Khao Sok Forest Immersion",
    "aa_name": "Khao Sok Forest Immersion",
    "aa_summary": "Five nights inside Khao Sok National Park, one of Southeast Asia's oldest rainforest systems, staying at a lakeside floating camp and a jungle lodge at the park boundary. The schedule moves between guided night walks through the primary forest, early morning boat patrols on Cheow Lan Lake, and time in the park's limestone interior where the guide leads without fixed trail, reading the forest floor for animal sign.",
    "aa_highlights": [
      "Night walk in primary Khao Sok rainforest with a naturalist guide, headtorch off for the final thirty minutes",
      "Pre-dawn kayak on Cheow Lan Lake to observe hornbill and great cormorant roosting colonies before the tourist longtails depart",
      "Three hours with a researcher from the park's wildlife monitoring team discussing gaur and clouded leopard sign in the western sector",
      "Aftrnoon swimming below a limestone cliff overhang reachable only by a forty-minute forest approach",
      "Evening meal on the floating camp deck, briefing on the following day's forest entry point using hand-drawn park maps"
    ],
    "quality_score": 7.5,
    "trip_type": "wildlife"
  },
  {
    "id": "GT-TH-004",
    "tenant_id": "aa-internal",
    "country": "Thailand",
    "src_name": "Sukhothai and the Central Plains",
    "aa_name": "Sukhothai and the Central Plains",
    "aa_summary": "A considered journey through the heartland of early Thai civilisation, moving north from Bangkok by private vehicle to spend three days among the twelfth-century ruins of Sukhothai and the quieter satellite site of Si Satchanalai, where almost no tour groups reach. The itinerary is built around the rhythm of the archaeological site — early morning when the light angles low across the lotus ponds and stone Buddhas — with afternoons reserved for smaller temples reached by bicycle or on foot.",
    "aa_highlights": [
      "Bicycle circuit of Sukhothai Historical Park at dawn, arriving at Wat Mahathat before the first park shuttle",
      "Guided access to Wat Phra Si Rattana Mahathat at Si Satchanalai with a heritage archaeologist from the Fine Arts Department",
      "Kilnside visit at the Sawankhalok ceramic district with a local collector who documents the royal kiln tradition",
      "Evening at Wat Saphan Hin — the hilltop shrine reached by a fifteen-minute walk — positioned for the best light on the plains",
      "Private session with a Sukhothai-period bronze specialist at the Ramkhamhaeng National Museum"
    ],
    "quality_score": 7.5,
    "trip_type": "cultural"
  },
  {
    "id": "GT-TH-005",
    "tenant_id": "aa-internal",
    "country": "Thailand",
    "src_name": "Andaman Sea Sail and Shore",
    "aa_name": "Andaman Sea Sail and Shore",
    "aa_summary": "A private charter through the limestone archipelago of Phang Nga Bay and the quieter southern islands toward Koh Lanta, moving by sailing yacht at a pace that allows for extended time at anchor in bays that day-trip boats can reach only briefly. The itinerary avoids the mass-tourism coves and routes instead through islands with no permanent infrastructure, stopping at fishing settlements accessible only by sea.",
    "aa_highlights": [
      "Full-day passage under sail through the sea caves of Phang Nga Bay, anchoring in a lagoon accessible only at mid-tide",
      "Snorkelling the live coral gardens off Koh Rok Nok, reached at dawn before visibility drops with the afternoon current",
      "Sunset anchorage below the vertical limestone wall of Koh Panak, watching swiftlets return to their cliff roosts",
      "Evening on deck off Koh Yao Noi, arranged in coordination with a local fisherman for a lantern-lit seafood meal",
      "Kayak passage through the mangrove channels of Koh Hong at low tide, returning to the yacht as the tide refloods the root system"
    ],
    "quality_score": 8.0,
    "trip_type": "sailing"
  },
  {
    "id": "GT-BT-001",
    "tenant_id": "aa-internal",
    "country": "Bhutan",
    "src_name": "Paro Valley High Routes",
    "aa_name": "Paro Valley High Routes",
    "aa_summary": "Ten days in the Paro Valley and the ridgelines above it, including the high approach toward Jomolhari base that most itineraries treat as a full expedition but which, in private form with good acclimatisation days built in, yields one of the kingdom's finest high-altitude perspectives without full expedition logistics. The lower Paro days are structured around the valley's dzongs and farmhouses rather than the monastery circuit.",
    "aa_highlights": [
      "Ascent of the Taktsang approach trail in pre-dawn darkness, arriving at the cliff-face monastery as light reaches the gorge",
      "High camp night at approximately 4,200m on the Jomolhari approach, with Jomolhari's north face visible in clear conditions",
      "Full-day walk between Drukgyel Dzong and Shana along the mule track used by border traders through the late twentieth century",
      "Morning with a Paro farmhouse family during the barley harvest, helping with the threshing and staying for a home-cooked meal",
      "Evening briefing with the journey's licensed Bhutanese guide on the political geography of the Bhutan-Tibet border zone"
    ],
    "quality_score": 8.0,
    "trip_type": "trekking"
  },
  {
    "id": "GT-BT-002",
    "tenant_id": "aa-internal",
    "country": "Bhutan",
    "src_name": "Thimphu Tsechu Festival Circuit",
    "aa_name": "Thimphu Tsechu Festival Circuit",
    "aa_summary": "An eight-day private circuit timed to the Thimphu Tsechu, Bhutan's largest festival, with days arranged to move between Thimphu's festival grounds and the quieter valley circuits of Punakha and Wangdue Phodrang, where local tsechus — smaller and unannounced to outside visitors — sometimes occur in the same week. The itinerary is designed by a guide with twenty years of festival access and adjusted annually to the calendar.",
    "aa_highlights": [
      "Full day at the Thimphu Tsechu courtyard, positioned at the inner ring for the morning cham dances with the guide explaining lineage of each masked form",
      "Private viewing of the Thongdrel unfurling at dawn on the final festival morning from the dzong's upper gallery",
      "Afternoon at Chimi Lhakhang, the fertility temple below Punakha, timed to avoid the group tours that arrive between ten and two",
      "Walk along the Mo Chhu river from Punakha Dzong to the Khamsum Yulley Namgyal Chorten, returning by farmland path",
      "Evening discussion with the journey's guide on the administrative role of the Thimphu Tsechu in modern Bhutanese governance"
    ],
    "quality_score": 7.5,
    "trip_type": "cultural"
  },
  {
    "id": "GT-BT-003",
    "tenant_id": "aa-internal",
    "country": "Bhutan",
    "src_name": "Bumthang Sacred Valleys",
    "aa_name": "Bumthang Sacred Valleys",
    "aa_summary": "A journey east from Thimphu across the Black Mountains to the Bumthang valleys, the spiritual heartland of Bhutan, where four separate valley systems contain some of the kingdom's oldest temples and the country's densest concentration of sacred sites. The journey is timed around the harvest season when the apple orchards above Jakar are in production and the valley paths carry local traffic rather than visitors.",
    "aa_highlights": [
      "Full day at Jambay Lhakhang, one of Bhutan's 108 geomantic temples, with the monastery's own scholar explaining the site's founding cartography",
      "Morning walk through Kurje Lhakhang's garden courtyard in autumn mist, before the day's first visitors arrive by vehicle",
      "Afternoon with a traditional black-powder paper maker at a Bumthang farmhouse, part of a craft preservation programme",
      "Crossing the Pelela Pass on foot in clear weather, with a 360-degree view across the Black Mountains toward the Tibetan plateau",
      "Evening at a Jakar farmhouse during apple pressing season, staying for a meal of red rice and buckwheat pancakes"
    ],
    "quality_score": 7.5,
    "trip_type": "cultural"
  },
  {
    "id": "GT-BT-004",
    "tenant_id": "aa-internal",
    "country": "Bhutan",
    "src_name": "Snowman Trek Approach — Laya Circuit",
    "aa_name": "Snowman Trek Approach — Laya Circuit",
    "aa_summary": "The Laya circuit — the accessible southern loop of the legendary Snowman Trek — traversed in private over fourteen days with a trekking crew that has completed the full route more than thirty times. The journey leaves the Paro valley at Shana, climbs through rhododendron forest to the high meadows above Gasa, and descends into the Laya village at 3,840m: a semi-nomadic community of around two thousand whose women wear the distinctive conical bamboo hats of the Layap people.",
    "aa_highlights": [
      "Crossing the Sinche La pass at 5,005m in the blue hour before sunrise, with the Jomolhari massif to the south",
      "Two nights in Laya village, meeting the community through the guide's existing relationships with Layap families",
      "Steep descent through old-growth juniper forest between Rodophu camp and the Gasa hot springs on day ten",
      "Briefing by a Royal Bhutan Army mountain guide on the Snowman Trek's full route and the logistics of its eleven high passes",
      "Final descent to Punakha via the Mo Chhu gorge, arriving at the dzong by river trail rather than road"
    ],
    "quality_score": 8.5,
    "trip_type": "trekking"
  },
  {
    "id": "GT-VN-001",
    "tenant_id": "aa-internal",
    "country": "Vietnam",
    "src_name": "Sapa Highland Traverse",
    "aa_name": "Sapa Highland Traverse",
    "aa_summary": "A week based in and around the Sapa highlands, moving between the town's remaining French-era buildings and the valley trails below Fansipan that connect H'mong and Red Dzao villages across a landscape that changes from rice terraces to pine-covered ridges within a single morning's walk. The itinerary uses a single base lodge rather than moving nightly, allowing deeper daily movement without logistics overhead.",
    "aa_highlights": [
      "Dawn ridge walk from Sapa to the viewpoint above Muong Hoa valley before the cloud burns off — a two-hour return that few visitors wake early enough to attempt",
      "Full-day trek from Sapa town to Ban Ho village via the Golden Stream Valley, staying overnight with a Black H'mong family",
      "Morning at the Bac Ha Sunday market, the largest ethnic minority market in the region, arriving by private vehicle before the tour coaches",
      "Afternoon brocade weaving session with a Red Dzao artisan in Ta Phin village, documented on the guide's own camera",
      "Early breakfast on the hotel terrace watching the rice harvest in the valley below — a September-only phenomenon"
    ],
    "quality_score": 7.0,
    "trip_type": "trekking"
  },
  {
    "id": "GT-VN-002",
    "tenant_id": "aa-internal",
    "country": "Vietnam",
    "src_name": "Central Coast Heritage Circuit",
    "aa_name": "Central Coast Heritage Circuit",
    "aa_summary": "Ten days along Vietnam's most historically layered coastline, connecting the imperial capital of Hue with the merchant port of Hoi An across a landscape containing Cham towers, French administrative buildings, and the country's finest surviving domestic architecture. The itinerary gives priority to the sites that require advance arrangement — the restricted inner courts of the Hue Citadel, the lesser-visited tube houses of Hoi An's southern quarter — over the standard circuit.",
    "aa_highlights": [
      "Private access to the Hue Citadel's restricted Mieu Temple complex at dawn with an Imperial Court researcher from Hue University",
      "Full-day cycle from Hoi An south to the fishing village of An Bang, returning via the quieter backroads of the Cam Nam island",
      "Two hours at My Son Sanctuary in the first hour after opening, before tourist crowds, with a guide who specialises in Cham architectural history",
      "Evening on a Thu Bon River boat during the lantern festival's quiet shoulder period, lit by a single guide lamp rather than the commercial fleet",
      "Afternoon session with a Hoi An master craftsman producing traditional silk lanterns in a family workshop behind the Japanese Covered Bridge"
    ],
    "quality_score": 7.5,
    "trip_type": "cultural"
  },
  {
    "id": "GT-VN-003",
    "tenant_id": "aa-internal",
    "country": "Vietnam",
    "src_name": "Phong Nha Cave Expedition",
    "aa_name": "Phong Nha Cave Expedition",
    "aa_summary": "Six days in the Phong Nha-Ke Bang system, one of the world's most extensive cave networks, with access to the Tu Lan cave system — a multi-chamber route involving river swimming, jungle approach, and overnight camping inside the cave's twilight zone — alongside day exploration of the more accessible Paradise and Phong Nha river caves. The operator holds one of the limited annual permits for Tu Lan overnight access.",
    "aa_highlights": [
      "Two-day Tu Lan cave expedition with overnight camp inside the Hang Tien cave chamber, reached by 4km jungle approach and river crossing",
      "Swimming the underground lake inside Tu Lan cave at dawn on day two, the cave's ceiling visible in headtorch detail above glasslike water",
      "Guided tour of Paradise Cave's inner section with a caving specialist, beyond the tourist boardwalk to the silent formations",
      "Evening at a Vietnamese farmhouse in the Chay River valley, with the Tu Lan team — all local guides — for a shared meal before the expedition",
      "Kayak passage along the Chay River through the Son Trach valley at last light, the karst towers reflecting in the still water"
    ],
    "quality_score": 8.0,
    "trip_type": "adventure"
  },
  {
    "id": "GT-JP-001",
    "tenant_id": "aa-internal",
    "country": "Japan",
    "src_name": "Kumano Kodo Pilgrimage Walk",
    "aa_name": "Kumano Kodo Pilgrimage Walk",
    "aa_summary": "A private traverse of the Nakahechi route of the Kumano Kodo — the thousand-year-old pilgrimage trail that links Osaka's outskirts with the three grand shrines of Kumano — walking between four to eight hours each day on trails that are maintained to their original stone-paved condition, staying in ryokan and small minshuku selected for access to onsen and position within the villages rather than for profile.",
    "aa_highlights": [
      "Three-day continuous walk on the Nakahechi route between Takijiri-oji and Hongu Taisha, following the imperial pilgrimage stones",
      "Dawn arrival at Hongu Taisha after an overnight ryokan at Chikatsuyu, entering the shrine in the first light before the morning ceremony",
      "Full-day route via the Dainichi-goe pass to the clifftop shrine of Nachi Taisha, with Nachi Waterfall visible from the final ridge approach",
      "Evening kaiseki meal at a Kawayu Onsen ryokan, with access to the river-bed hot spring open only between November and February",
      "Briefing by a retired Kumano shrine priest on the Dual Mandala cosmology that underlies the pilgrimage's directional logic"
    ],
    "quality_score": 8.0,
    "trip_type": "trekking"
  },
  {
    "id": "GT-JP-002",
    "tenant_id": "aa-internal",
    "country": "Japan",
    "src_name": "Tohoku Slow Rail and Coast",
    "aa_name": "Tohoku Slow Rail and Coast",
    "aa_summary": "An eleven-day passage through Tohoku — Japan's northern Honshu region, still undervisited relative to its landscapes and depth of craft tradition — travelling primarily by local rail rather than shinkansen, stopping at fishing ports, lacquerware workshops, and the forested interior valleys that contain Japan's most intact cedar temple precincts. The itinerary was designed around the 2011 coastal restoration projects, several of which are now significant cultural landmarks in their own right.",
    "aa_highlights": [
      "Full day along the Sanriku Coast by local train between Hachinohe and Miyako, with the guide identifying reconstruction landmarks and pre-disaster communities",
      "Morning at the Chusonji temple complex in Hiraizumi — a UNESCO World Heritage precinct — before the tour groups from Tokyo arrive by bus",
      "Afternoon with a Tohoku lacquerware master in Aizu-Wakamatsu, observing the maki-e technique that takes a decade to achieve fluency",
      "Bow from the ferry deck as it enters the pine-island bay of Matsushima, Japan's most painted classical landscape, in rain",
      "Evening conversation with a Sendai-based poet whose work focuses on the post-2011 Tohoku landscape — arranged through the guide's network"
    ],
    "quality_score": 7.5,
    "trip_type": "rail_journey"
  },
  {
    "id": "GT-JP-003",
    "tenant_id": "aa-internal",
    "country": "Japan",
    "src_name": "Shikoku 88 Temple Circuit — Selected Stages",
    "aa_name": "Shikoku 88 Temple Circuit — Selected Stages",
    "aa_summary": "Twelve days walking selected stages of the Shikoku Henro — the 1,200km pilgrimage circuit of eighty-eight temples associated with the monk Kukai — in the distinctive white coat and sedge hat of the ohenro-san pilgrim, staying in temple lodgings and small minshuku, eating with other pilgrims where the trail lodges allow communal dining. The selection of stages prioritises the Tosa coast's most isolated stretches and the forest interior of Ehime, where the trail is least altered from its Edo-period condition.",
    "aa_highlights": [
      "Walking the Cape Muroto headland stage in the pre-dawn hours, arriving at Hotsumisakiji Temple in the early light with a small group of white-coated pilgrims",
      "Three nights in temple lodging at Tosa-area henro-yado, eating the communal vegetarian meals that accompany the pilgrim circuit",
      "Coastal stage walk along the Tosa Bay cliffs between Temples 37 and 38, the Pacific breaking against the volcanic headlands below",
      "Private briefing at the Koyasan mountain headquarters of the Shingon sect — the spiritual origin of the Shikoku circuit — before departure",
      "Farewell exchange at the final stage with a retired salaryman who has walked the full 88-temple circuit eleven times"
    ],
    "quality_score": 8.0,
    "trip_type": "trekking"
  },
  {
    "id": "GT-NP-001",
    "tenant_id": "aa-internal",
    "country": "Nepal",
    "src_name": "Langtang Valley Trek",
    "aa_name": "Langtang Valley Trek",
    "aa_summary": "Ten days in the Langtang Valley — Nepal's closest major trek to Kathmandu and yet among its least visited — walking north from Syabrubesi through a valley defined by the 2015 earthquake's aftermath and the community's determination to rebuild around restored trails and new tea houses. The route reaches Kyanjin Gompa at 3,870m and the optional high point at Tserko Ri, with acclimatisation days structured around the cheese factory, the monastery, and the permanent glacier visible from the settlement.",
    "aa_highlights": [
      "Full ascent to Tserko Ri at 4,984m in the pre-dawn hours, reaching the summit as the Langtang and Ganesh Himal ranges emerge in first light",
      "Afternoon at the Kyanjin Gompa cheese factory with the cooperative's head, learning the Tibetan-origin technique used by Tamang settlers",
      "Walk through the ghost-meadow site of the 2015 landslide above Langtang village, briefed on the community recovery by a local guide who was present",
      "Two nights at Kyanjin, the second spent in near-silence above the valley with a fire and a single altitude-acclimatised companion",
      "Morning in the Kathmandu Durbar Square at dawn before departure — a discipline the guide builds into every Langtang itinerary"
    ],
    "quality_score": 7.0,
    "trip_type": "trekking"
  },
  {
    "id": "GT-NP-002",
    "tenant_id": "aa-internal",
    "country": "Nepal",
    "src_name": "Mustang Upper Kingdom Circuit",
    "aa_name": "Mustang Upper Kingdom Circuit",
    "aa_summary": "A full circuit through Upper Mustang — the former Lo Kingdom, restricted to permit holders and accessible only by air and then on foot — from Jomsom's windswept airstrip north to the walled capital of Lo Manthang. The landscape is Tibetan plateau in character: dry, ochre, and vertical, with cave monasteries cut into the cliff faces and a royal palace at the valley's end still occupied by the Lo King's household. The journey is structured in a fourteen-day private format that allows non-trekking rest days in Lo Manthang.",
    "aa_highlights": [
      "Three days in Lo Manthang, the walled royal capital, with access to the restored fourteenth-century murals inside Thubchen Gompa through the Mustang Eco Museum project",
      "Trekking the ancient salt trade route between Lo Gekar and Ghami, following the carved mani walls built by traders across eight centuries",
      "Private audience with an official of the Lo King's household — arranged through the guide's decades of relationship in Upper Mustang",
      "Afternoon at the sky cave complex of Chhosar, where ancient Bon ritual objects and human remains were discovered in the 1990s",
      "Evening at a Lo Manthang rooftop, the Tibetan plateau visible to the north in the last hour before the border-zone curfew"
    ],
    "quality_score": 8.5,
    "trip_type": "trekking"
  },
  {
    "id": "GT-KH-001",
    "tenant_id": "aa-internal",
    "country": "Cambodia",
    "src_name": "Angkor Beyond the Circuit",
    "aa_name": "Angkor Beyond the Circuit",
    "aa_summary": "Seven days in the extended Angkorian world, beginning at Siem Reap's grand temples and moving north to the remote sites that receive fewer than a hundred visitors a day — Koh Ker's pyramid-form Prasat Thom and the cliff-edge temple of Preah Vihear on the Thai border, reached by a road that was still contested territory within living memory. An archaeologist from Siem Reap's heritage institute accompanies the northern circuit.",
    "aa_highlights": [
      "Private access to Angkor Wat's western causeway at 5am with an archaeologist, two hours before the general opening",
      "Full day at Koh Ker's jungle-encircled pyramid with a Heritage Watch Cambodia researcher, examining the ongoing unexcavated sectors",
      "Dawn at Preah Vihear temple on the Thai-Cambodia escarpment, the Cambodian plains 500m below and the Thai tableland at the same elevation",
      "Afternoon with a silk weaving family in Kbal Spean village, where a revival programme has re-established a pre-war design tradition",
      "Evening boat on the Tonle Sap Lake as the sun sets behind the floating village at Chong Kneas, outside the tourist boat schedule"
    ],
    "quality_score": 7.5,
    "trip_type": "cultural"
  },
  {
    "id": "GT-LA-001",
    "tenant_id": "aa-internal",
    "country": "Laos",
    "src_name": "Mekong River Village Journey",
    "aa_name": "Mekong River Village Journey",
    "aa_summary": "Eight days on the upper Mekong between Luang Prabang and the Thai border crossing at Huay Xai, travelling partly by private longtail and partly on foot through villages reachable only from the river, staying in guesthouses chosen for their position in the village rather than for facilities. The itinerary is not the two-day slow boat to Huay Xai — it is a considered movement through the same stretch of water over a week, with daily stops that the slow boat passes without landing.",
    "aa_highlights": [
      "Full-day departure from Luang Prabang by longtail at dawn, stopping at three river villages before noon that receive no scheduled tourist traffic",
      "Afternoon walk from the landing at Ban Pak Ou into the interior to reach the limestone cave shrines at a different approach than the tourist ferries use",
      "Two nights at Pak Beng with a local guide who grew up on the river and reads the Mekong's seasonal water levels as a navigation tool",
      "Evening with a Khmu weaving family in a village one hour upstream of Pak Beng, reached only by the journey's private boat",
      "Final morning crossing to Huay Xai by longtail at first light, watching the Thai bank come forward as Laos recedes behind"
    ],
    "quality_score": 7.0,
    "trip_type": "river_journey"
  },
  {
    "id": "GT-MN-001",
    "tenant_id": "aa-internal",
    "country": "Mongolia",
    "src_name": "Gobi Desert Camel Traverse",
    "aa_name": "Gobi Desert Camel Traverse",
    "aa_summary": "Ten days in the Mongolian Gobi — the southern desert basin that extends five hundred kilometres from Dalanzadgad toward the Chinese border — with three days of camel traverse across the Khongoryn Els dune system, sleeping in ger camps positioned by the guide for wind direction rather than proximity to the tourist route. The itinerary includes the Flaming Cliffs of Bayanzag and the ice valleys of Yolyn Am, where a permanent glacier survives into summer.",
    "aa_highlights": [
      "Three-day Bactrian camel traverse of the Khongoryn Els, crossing the main dune ridge on day two and camping on the far side in a guide-owned ger",
      "Dawn at the Flaming Cliffs of Bayanzag, the ochre formation where Roy Chapman Andrews discovered the first dinosaur nests in 1922",
      "Ice canyon walk in Yolyn Am in July, when the permanent glacier remains a metre thick in the shaded gorge bottom",
      "Evening with a Gobi herder family during the late-summer ger relocation, helping load the camel train before the move",
      "Night sky observation at the Khongoryn Els camp — the Gobi's zero light-pollution environment produces one of the continent's best naked-eye skies"
    ],
    "quality_score": 7.5,
    "trip_type": "adventure"
  }
]


def seed():
    repo = GoldenTourRepository()
    seeded = 0
    for data in GOLDEN_TOURS:
        try:
            doc_id = repo.insert(data)
            print(f"  ✓ {data['id']} {data['country']} — {data['src_name'][:45]}")
            seeded += 1
        except Exception as e:
            print(f"  ✗ {data['id']} ERROR: {e}")
    
    print(f"\nSeeded: {seeded}/{len(GOLDEN_TOURS)}")
    print(f"Total in ChromaDB: {repo.count('aa-internal')}")
    return seeded


def verify():
    repo = GoldenTourRepository()
    print("\nVerification — sample queries:")
    tests = [
        ("Northern Highlands Traverse", "Thailand"),
        ("Paro Valley", "Bhutan"),
        ("Kumano Kodo", "Japan"),
    ]
    for name, country in tests:
        results = repo.query_similar(name, country, "aa-internal", n_results=2)
        print(f"  Query: '{name}' ({country})")
        for r in results:
            print(f"    → {r['aa_name'][:50]} (sim: {r['similarity']})")


if __name__ == "__main__":
    print("=" * 60)
    print("Seeding ChromaDB — 20 Golden Tours")
    print("=" * 60)
    seeded = seed()
    if seeded > 0:
        verify()
