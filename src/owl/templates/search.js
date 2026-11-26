/* Small offline metadata search. No source files, network, or model required. */
(function (root) {
  'use strict';
  const FORMAT = 'owl-discovery-v1';
  const generation = typeof document === 'undefined' ? '' :
    document.currentScript?.getAttribute('src')?.match(/^LIBRARY\/(INDEX\/[0-9a-f]{12})\/search\.js$/)?.[1] || '';
  const local = path => (generation || 'SEARCH') + '/' + path;
  const normalize = value => String(value || '').normalize('NFKC').toLowerCase().replace(/\s+/gu, ' ').trim();
  const tokens = value => [...new Set(normalize(value).match(/[\p{L}\p{N}]+/gu) || [])];
  function prepare(records) {
    if (!Array.isArray(records)) throw new Error('Invalid discovery records');
    return records.map(record => {
      if (!record || typeof record.id !== 'string' || typeof record.title !== 'string' || !safeHref(record.href)) throw new Error('Invalid discovery destination');
      const titles = [record.title, ...(record.aliases || [])].map(normalize);
      const headline = new Set(tokens(titles.join(' ')));
      const text = new Set(tokens([record.description, record.source_title, record.category, record.publisher,
        ...(record.labels || []), ...(record.shelves || [])].join(' ')));
      return {record, titles, headline, text};
    });
  }
  function eligible(r, shelf) {
    if (shelf === 'legacy') return r.legacy === true;
    if (shelf !== 'all-with-legacy' && r.legacy) return false;
    return ['all', 'all-with-legacy'].includes(shelf) || (r.shelves || []).includes(shelf);
  }
  function search(prepared, query, shelf = 'all', limit = 50) {
    const phrase = normalize(query), words = tokens(query);
    if (words.length > 32) throw new Error('Use at most 32 different search words.');
    if (!words.length) return [];
    const found = [];
    for (const {record, titles, headline, text} of prepared) {
      if (!eligible(record, shelf)) continue;
      let hits = 0, titleHits = 0;
      for (const word of words) {
        if (headline.has(word)) { hits++; titleHits++; }
        else if (text.has(word)) hits++;
      }
      if (!hits) continue;
      const exact = titles.includes(phrase), all = hits === words.length;
      found.push({record, score: (exact ? 100000 : all ? 10000 : 0) + hits * 100 + titleHits * 10});
    }
    found.sort((a, b) => b.score - a.score || a.record.title.localeCompare(b.record.title) || a.record.id.localeCompare(b.record.id));
    const seen = new Set();
    return found.filter(({record}) => {
      const key = record.href + '\0' + record.location;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    }).slice(0, limit);
  }
  function safeHref(href) {
    if (typeof href !== 'string' || !href || /^[\/\\]/.test(href)) return false;
    try {
      const path = decodeURIComponent(href.split('#')[0]);
      return !/[\x00-\x1f\\?:]/.test(path) && !path.split('/').some(p => !p || p === '.' || p === '..');
    } catch (_) { return false; }
  }
  function script(path) {
    return new Promise((resolve, reject) => {
      const tag = document.createElement('script');
      const finish = error => {
        clearTimeout(timeout);
        tag.remove();
        if (error) reject(Error(error));
        else resolve();
      };
      const timeout = setTimeout(() => finish('Loading local files timed out.'), 15000);
      tag.src = 'LIBRARY/' + path;
      tag.onload = () => finish();
      tag.onerror = () => finish('This viewer could not load the local files.');
      document.head.appendChild(tag);
    });
  }
  function isArchive(record) {
    return record.kind === 'article' || /\.zim(?:[a-z]{2})?$/i.test((record.destination || record.href).split('#')[0]);
  }
  const naturalWater = /\b(?:creeks?|rivers?|streams?|lakes?|rain(?: ?water)?|ponds?|springs?|brooks?|reservoirs?|wells?|snowmelt)\b/;
  const wherePeopleSubmerge = /\b(?:water|pools?|rivers?|lakes?|creeks?|streams?|ponds?|sea|ocean|surf|canals?|reservoirs?|bathtubs?|tub|wells?|deep end)\b/;
  // Keep the movement and the body of water in the same phrase.
  const entersWater = new RegExp(
    /\b(?:fell|fall\w*|slip\w*|tumbl\w*|plung\w*|went|got|jump\w*|knocked|swept)(?: \w+){0,3} (?:into|in|under)(?: \w+){0,4} /.source +
    wherePeopleSubmerge.source);
  const waterUse = phrase =>
    /\b(?:well water|flooded well|(?:runoff|sewage|flood ?waters?) .{0,40}(?:into|in) .{0,15}wells?)\b/.test(phrase) ||
    (naturalWater.test(phrase) || /\b(?:tap|drinking|flood|flooded|contaminated|untreated) water\b/.test(phrase)) &&
    /\b(?:drink(?:s|ing|able)?|potable|boil\w*|purif\w*|disinfect\w*|water treatment|for cooking|cook with|rinse dishes|wash\w* dishes|us(?:e|ing) (?:\w+ ){0,3}water|(?:can|could|should|may) (?:we|i|you) use (?:it|this|that)|(?:safely|safe to) use)\b/.test(phrase);
  const drowningVictim = phrase =>
    /\b(?:drown\w*|submersion injury|fell (?:\w+ ){0,3}overboard|swimmer|gasp\w*|not breathing|underwater|submerged|pulled out (?:limp|unconscious))\b/.test(phrase) ||
    entersWater.test(phrase) && /\b(?:i|he|she|they|someone|person|child|girl|boy|man|woman|friend|neighbor|neighbour|driver|passenger|son|daughter|dad|mom)(?: just)? (?:fell|slip\w*|tumbl\w*|plung\w*|got swept)\b/.test(phrase);
  const treatmentRequest = phrase => waterUse(phrase) && !drowningVictim(phrase);
  const swallowableObject = /\b(?:batter(?:y|ies)|button cells?|coins?|penn(?:y|ies)|dimes?|nickels?|magnets?|toys?|lego|beads?|marbles?|buttons?|screws?|small objects?|plastic pieces?)\b/;
  const sharpObject = /\b(?:nails?|tacks?|screws?|needles?|pins?|splinters?|shards?|glass|barbs?|thorns?|wire|(?:sharp|rusty|dirty) metal)\b/;
  // Ordered from specific situations to the more general injuries they can
  // resemble. Each row names a selected catalog document and its physical PDF
  // page, or a named article in the selected WikiMed edition.
  const reviewedRoutes = [
    ['electrical-fire', 'Electrical fire safety', 'cert', 175, [
      /\b(?:electrical fire|overloaded (?:outlet|circuit))\b/,
      [/\b(?:outlet|socket|plug|breaker|power strip|wiring)\b/, /\b(?:smok\w*|spark\w*|on fire|burning smell|smells? burnt|scorch\w*)\b/],
    ]],
    ['carbon-monoxide', 'Carbon monoxide poisoning', 'wikimed_en', 'Carbon_monoxide_poisoning', [
      /\b(?:carbon monoxide|co (?:alarm|poisoning)|generator exhaust)\b/,
      [/\b(?:generator|charcoal|exhaust|heater|car engine)\b/, /\b(?:indoors|inside|garage|basement|enclosed|tent)\b/,
        /\b(?:headache|dizz\w*|nause\w*|passed out|faint\w*|sick|generator)\b/],
    ]],
    ['gas-leak', 'Natural gas leak', 'cert', 176, [
      /\b(?:gas leak|leaking gas|smells? (?:like |of )?(?:natural )?gas|gas smell|gas shutoff)\b/,
      [/\b(?:rotten eggs|hiss\w*)\b/, /\b(?:stove|gas|burner|furnace|oven|propane)\b/],
    ]],
    ['house-fire', 'House fire and smoke', 'cert', 173, [
      /\b(?:house fire|home fire|building (?:is )?on fire|fire escape|smoke inhalation)\b/,
      [/\b(?:smoke|fire|flames)\b/, /\b(?:fill\w*|trapped|hallway|stairs|upstairs|bedroom|house|escape|apartment)\b/],
    ]],
    ['flood', 'Flood safety', 'fema_are_you_ready_2020', 11, [
      /\b(?:floodwaters?|flash floods?|flood safety|flooded (?:road|car)|rising (?:flood|water))\b/,
      [/\b(?:water|creek|river)\b/, /\b(?:rising|overflow\w*|over the road|coming in|trapped|stranded)\b/,
        /\b(?:car|truck|road|vehicle|bridge|doors)\b/],
      [/\b(?:creek|river|stream)\b/, /\b(?:overflow\w*|burst its banks)\b/],
      /^floods?$/,
    ]],
    ['earthquake', 'Earthquake safety', 'fema_are_you_ready_2020', 10, [
      /\b(?:earthquake|ground (?:is )?(?:shaking|moving)|drop cover and hold)\b/,
      [/\b(?:room|house|floor|building|ground)\b/, /\b(?:shak\w*|trembl\w*|rumbl\w*)\b/, /\b(?:whole|fall\w*|mov\w*|what do)\b/],
    ]],
    ['postpartum', 'Bleeding after birth', 'hesperian_en_midw_2026_13', 3, [
      /\b(?:postpartum h(?:a)?emorrhage|postpartum bleeding|bleeding after (?:birth|delivery))\b/,
      [/\b(?:blood|bleed\w*|hemorrhag\w*|haemorrhag\w*)\b/,
        /\b(?:after .{0,24}(?:birth|delivery|having (?:a|the) baby)|gave birth|(?:baby|placenta) .{0,16}(?:born|came out|delivered))\b/],
    ]],
    ['chemical-eye', 'Chemical eye injury', 'wikimed_en', 'Chemical_eye_injury', [
      /\b(?:chemical eye injur\w*|eye wash|chemicals? in (?:my |the )?eyes?)\b/,
      [/\beyes?\b/, /\b(?:chemical\w*|bleach|cleaner|detergent|cleaning (?:spray|fluid|solution)|acid|battery (?:liquid|fluid)|ammonia)\b/],
    ]],
    ['electric-shock', 'Electrical injury', 'wikimed_en', 'Electrical_injury', [
      /\b(?:electric(?:al)? shock\w*|electrical injur\w*|electrocut\w*|shock from .{0,20}(?:outlet|wire|cord)|(?:touched|grabbed|holding) .{0,24}(?:live wire|power line|exposed wire))\b/,
      [/\b(?:wire|wires|cable|cord|outlet|socket|power line|current)\b/,
        /\b(?:shock\w*|zapp\w*|knocked .{0,12}down|cant let go|locked up|tingl\w*|fell|collaps\w*)\b/,
        /\b(?:touch\w*|grab\w*|current|live|bare|shock\w*|zapp\w*)\b/],
      [/\b(?:fence|appliance|washer|dryer|fridge|freezer|washing machine|oven|stove|toaster|blender|kettle|microwave|power tool)\b/,
        /\b(?:jolt\w*|shock\w*|zapp\w*|current|cant let go|couldnt let go|could not let go|electrocut\w*)\b/],
    ]],
    ['drowning', 'Drowning', 'wikimed_en', 'Drowning', [
      /\b(?:drown\w*|near drowning|submersion injury)\b/,
      entersWater,
      /\b(?:fell|fallen|went|washed|swept|knocked) (?:\w+ ){0,3}overboard\b/,
      [/\b(?:canoes?|kayaks?|boats?|rafts?|ferr(?:y|ies)|ships?|dingh(?:y|ies))\b/,
        /\b(?:fell|slip\w*|went|knocked|swept) (?:\w+ ){0,3}(?:off|over) (?:\w+ ){0,3}(?:side|edge|rail)\b/],
      [wherePeopleSubmerge,
        /\b(?:pulled|dragged|rescued|underwater|fell in|sank|submerged|gasp\w*|not breathing)\b/,
        /\b(?:swimmer|swimming|breath\w*|gasp\w*|unconscious|unresponsive|underwater|submerged|limp)\b/],
    ]],
    ['anaphylaxis', 'Anaphylaxis and severe allergic reactions', 'msf_guideline-170-en', 14, [
      /\b(?:anaphylax\w*|anaphylactic|severe allergic reaction|epipen|epinephrine (?:pen|autoinjector))\b/,
      [/\b(?:sting|stung|allerg\w*|hives|peanuts?|shellfish|medicine|medication)\b/,
        /\b(?:(?:throat|tongue|lips?|mouth|face) .{0,26}(?:swell\w*|swollen|tight|closing)|(?:swell\w*|swollen) .{0,16}(?:throat|tongue|lips?|mouth|face)|cant breathe|cannot breathe|barely breathe|trouble breathing|wheez\w*)\b/],
      [/\b(?:ate|eating|food|meal|new medication)\b/, /\b(?:tongue|throat|lips?|mouth|face)\b/, /\b(?:swell\w*|swollen|closing)\b/],
    ]],
    ['choking', 'Choking first aid', 'medical_bec', 155, [
      /\b(?:choking|choked|airway obstruction|heimlich|back blows|food (?:is )?stuck|something stuck .{0,14}throat)\b/,
      [/\b(?:food|eating|swallow\w*|throat)\b/, /\b(?:cant (?:speak|make a sound|cough|breathe)|cannot (?:speak|cough|breathe)|turning blue|wedged)\b/],
    ]],
    ['cold-exposure', 'Hypothermia', 'cert', 114, [
      /\b(?:hypothermia|stopped shivering|dangerously cold|cold exposure)\b/,
      [/\b(?:cold|freezing|icy|snow|soaked)\b/, /\b(?:shiver\w*|confus\w*|drowsy|slurr\w*|cant get warm)\b/],
    ]],
    ['frostbite', 'Frostbite', 'cert', 114, [
      /\b(?:frostbite|frostnip|frozen skin)\b/,
      [/\b(?:toes?|fingers?|skin|nose|ears?|hands?|feet)\b/, /\b(?:numb|waxy|turn\w* white|went white)\b/,
        /\b(?:cold|snow|ice|freez\w*|white|pale)\b/],
    ]],
    ['heat-illness', 'Heat stroke and heat illness', 'fema_are_you_ready_2020', 10, [
      /\b(?:heat ?stroke|heat exhaustion|heat illness|overheat\w* .{0,18}confus\w*)\b/,
      [/\b(?:heat|hot|sun|overheat\w*)\b/,
        /\b(?:confus\w*|disorient\w*|talking nonsense|not making sense|passed out|collaps\w*|stopped sweating|dizz\w*)\b/],
    ]],
    ['stroke', 'Stroke and sudden weakness', 'medical_bec', 139, [
      /\b(?:stroke (?:signs|symptoms|first aid)|slurred speech|(?:having|had) a stroke|facial droop)\b/,
      [/\b(?:face|mouth|smile|(?:one|left|right) side)\b/,
        /\b(?:droop\w*|numb|weak\w*|uneven|lopsided|cant lift|wont move|paraly\w*|garbled)\b/],
      [/\b(?:sudden\w*|(?:one|left|right) side|weak\w*)\b/,
        /\b(?:words? .{0,18}(?:garbled|wrong|slurr\w*)|cant (?:talk|speak)|slurr\w* .{0,14}(?:words|speech))\b/],
      /^stroke$/,
    ]],
    ['heart-attack', 'Heart attack and chest pain', 'medical_bec', 203, [
      /\b(?:heart attack|myocardial infarction|chest (?:pain|pressure|tightness|heaviness)|pressure (?:on|in) .{0,14}chest)\b/,
      [/\bchest\b/, /\b(?:arm|jaw|crush\w*|squeez\w*|heavy|pressure|tight\w*)\b/, /\b(?:pain|hurts?|sitt\w*|sweat\w*|squeez\w*|crush\w*)\b/],
    ]],
    ['resuscitation', 'CPR and cardiac arrest', 'wikimed_en', 'Cardiopulmonary_resuscitation', [
      /\b(?:cpr|aed|resuscitation|chest compressions|cardiac arrest|not breathing|stopped breathing|isnt breathing|no pulse)\b/,
      [/\b(?:collaps\w*|faint\w*|passed out|unconscious|unresponsive|wont wake|cant wake)\b/,
        /\b(?:gasp\w*|is (?:barely|hardly) breathing|no breaths?)\b/],
      [/\b(?:(?:blue|bluish|gr[ae]y) (?:lips?|face)|(?:lips?|face) (?:turned|turn\w*|look\w*|are) (?:blue|bluish|gr[ae]y))\b/,
        /\b(?:cant|cannot) tell (?:if|whether)\b/, /\bbreath\w*\b/],
    ]],
    ['unresponsive', 'Unresponsive person and fainting', 'hesperian_en_wtnd_2025_10', 4, [
      /\b(?:unconscious|unresponsive|faint(?:ed|ing|s)|passed out|blacked out|lost consciousness|not (?:responding|waking)|(?:isnt|arent) (?:waking|responding)|(?:wont|cant|cannot) (?:wake|come (?:to|round|around)|respond))\b/,
      [/\b(?:collaps\w*|lying|shook|shake)\b/, /\b(?:waking|no response|eyes shut|wont answer|not moving)\b/],
    ]],
    ['swallowed-object', 'Swallowed objects and foreign bodies', 'wikimed_en', 'Foreign_body', [
      /\b(?:foreign body ingestion|swallowed (?:a |an |the )?objects?)\b/,
      /\b(?:swallow\w*|gulp\w*) (?:\w+ ){0,2}quarters?\b(?! (?:of|cup|spoon|hour|inch))/,
      [swallowableObject,
        /\b(?:swallow\w*|gulp\w*|ate|eaten|ingest\w*|gobbl\w*|down (?:his|her|their|my|the) throat|put (?:\w+ ){0,3}in (?:his|her|their|my|the) mouth)\b/],
      [/\b(?:batter(?:y|ies)|button cells?|magnets?)\b/, /\b(?:missing|gone)\b/,
        /\b(?:child|kid|toddler|baby|mouth)\b/],
    ]],
    ['ingestion', 'Poisoning and accidental ingestion', 'wikimed_en', 'Poisoning', [
      /\b(?:accidental poisoning|poison control|overdose|swallowed poison|drank poison|poisoning first aid)\b/,
      [/\b(?:swallow\w*|drank|drink\w*|ate|eaten|gulp\w*|(?:took|had) a (?:sip|swig|mouthful|gulp)|unknown amount|open bottle|too many)\b/,
        /\b(?:poison\w*|bleach|cleaner|detergent|pills?|tablets?|medicine|medication|antifreeze|rat bait)\b/],
      /^poisoning$/,
    ]],
    ['snakebite', 'Snakebite', 'msf_guideline-170-en', 355, [
      /\b(?:snakebites?|snake (?:bite|bit|venom)|bitten by (?:a |the )?snake)\b/,
      [/\b(?:snake|slither\w*)\b/, /\b(?:bit\w*|puncture\w*|fang\w*)\b/],
    ]],
    ['animal-bite', 'Animal bites and rabies', 'msf_guideline-170-en', 258, [
      /\b(?:animal bites?|dog bites?|cat bites?|rabies exposure|rabies after)\b/,
      [/\b(?:dog|cat|animal|bat|raccoon|fox|stray)\b/,
        /\b(?:bite|bites|bit|bitten|sank .{0,12}teeth|broke the skin|scratch\w*|attack\w*|(?:tore|ripped) .{0,24}open)\b/],
    ]],
    ['insect-sting', 'Insect bites and stings', 'wikimed_en', 'Arthropod_bites_and_stings', [
      /\b(?:bee stings?|wasp stings?|insect (?:bites?|stings?)|hornet stings?|stung by)\b/,
      [/\b(?:bee|wasp|hornet|insect|scorpion)\b/, /\b(?:sting\w*|stung|bite|bitten)\b/],
    ]],
    ['newborn-fever', 'Fever and other danger signs in newborns', 'msf_guideline-449-en', 221, [
      [/\b(?:newborn|neonat\w*|(?:[1-4]|one|two|three|four) weeks? old|days? old)\b/,
        /\b(?:fever|temperature|thermometer|feels? hot|burning up)\b/],
    ]],
    ['infant-fever', 'Fever in young infants', 'msf_guideline-170-en', 35, [
      [/\b(?:baby|babies|infant|(?:[5-9]|1[0-2]|five|six|seven|eight|nine|ten|eleven|twelve) weeks? old|(?:[1-3]|one|two|three) months? old)\b/,
        /\b(?:fever|temperature|thermometer|feels? hot|burning up)\b/],
    ]],
    ['childbirth', 'Childbirth and delivery', 'hesperian_en_midw_2026_12', 14, [
      /\b(?:childbirth|giving birth|baby (?:is )?coming|birth at home|home birth|imminent delivery|head is crowning|(?:labor|labour) and (?:birth|delivery)|(?:deliver|catch) .{0,12}baby)\b/,
      [/\b(?:pregnant|contractions|labour|labor|baby)\b/, /\b(?:cant make it|need\w* to push|urge to push|water broke|can see .{0,14}head)\b/],
    ]],
    ['fracture', 'Fractures and broken bones', 'cert', 110, [
      /\b(?:fractures?|broken (?:bones?|arms?|legs?|ankle|wrist)|bone (?:is )?(?:sticking|poking) out)\b/,
      [/\b(?:ankle|wrist|arm|leg|bone)\b/, /\b(?:crooked|deform\w*|bent (?:the )?wrong way|odd angle|unnatural angle)\b/],
    ]],
    ['burn', 'First aid for burns and scalds', 'msf_guideline-170-en', 339, [
      /\b(?:scald\w*|burns? (?:first aid|treatment)|(?:treat|cool) .{0,14}(?:burns?|burned skin)|burn(?:t|ed) (?:my |his |her |their )?(?:skin|arm|hand|face|leg))\b/,
      [/\b(?:boiling|hot water|hot oil|steam|flame|fire|burn\w*)\b/, /\b(?:skin|arm|hand|leg|face|blister\w*|scald\w*|spilled|splashed)\b/],
      /^burns?$/,
    ]],
    ['bleeding', 'Controlling severe bleeding', 'cert', 101, [
      /\b(?:heavy bleeding|severe bleeding|(?:stop|control) .{0,12}bleed\w*|wont stop bleeding|(?:external )?h(?:a)?emorrhage|blood (?:spurting|gushing|pouring)|bleeding (?:badly|a lot))\b/,
      [/\b(?:blood|bleed\w*)\b/, /\b(?:wont stop|keeps bleeding|soak\w*|spurting|gushing|pouring|so much|a lot|losing)\b/],
      /^(?:bleeding|bleeding wound)$/,
    ]],
    ['puncture-wound', 'Puncture wounds and tetanus', 'hesperian_en_wtnd_2025_10', 15, [
      /\b(?:puncture wounds?|punctured (?:skin|foot|hand)|tetanus (?:shot|booster|risk)|lockjaw)\b/,
      [sharpObject, /\b(?:step\w* on|stood on|tro(?:d|dden) on|went through|stuck into|stab\w*|pierc\w*|pok\w*|punctur\w*)\b/],
      [sharpObject, /\b(?:hole|blood|wound|tetanus)\b/,
        /\b(?:foot|feet|heel|toes?|hand|palm|fingers?|arm|leg|skin|rusty|dirty)\b/],
      /^tetanus$/,
    ]],
    ['dehydration', 'Diarrhea, dehydration and oral rehydration', 'hesperian_en_wtnd_2025_13', 1, [
      /\b(?:dehydrat\w*|diarrh\w*|oral rehydration|watery (?:poop|stools?)|loose stools|(?:cant|cannot) keep (?:fluids|water) down)\b/,
      [/\b(?:not peeing|hasnt peed|no wet diapers|dry nappies)\b/, /\b(?:vomit\w*|throwing up|sick|dry mouth|diarrh\w*|watery)\b/],
    ]],
    ['drinking-water', 'Drinking water disinfection', 'water', 1, [
      /\b(?:drinking water (?:safe|disinfection|treatment)|water purification|purify water|disinfect water|boil water|make water (?:safe|drinkable))\b/,
      [/\b(?:tap water|well water|river water|stream water|drinking water|water .{0,15}drink)\b/,
        /\b(?:dirty|cloudy|contaminat\w*|safe|only|untreated|boil\w*)\b/],
      [naturalWater, /\b(?:drink\w*|potable|(?:fill|refill) (?:\w+ ){0,3}(?:bottle|canteen|flask)s?)\b/],
      [naturalWater, /\bwater\b/, /\b(?:safe|clean|purif\w*|disinfect\w*|treat\w*|boil\w*)\b/],
    ]],
    ['food-outage', 'Food safety during a power outage', 'fema_are_you_ready_2020', 13, [
      /\b(?:food safety .{0,20}(?:power|outage)|power (?:outage|cut) .{0,20}(?:food|fridge|freezer))\b/,
      [/\b(?:power|electricity|blackout|outage)\b/, /\b(?:fridge|refrigerator|freezer|thaw\w*|meat|milk|perishable\w*)\b/],
    ]],
    ['sanitation', 'Emergency sanitation and toilets', 'hesperian_en_cgeh_2012_07', 2, [
      /\b(?:emergency sanitation|toilet (?:wont|doesnt|cant) flush|no working toilets?|bucket toilet|human waste after)\b/,
      [/\b(?:toilets?|bathroom|latrine|human waste|sewer)\b/, /\b(?:no plumbing|without water|no (?:running )?water|nowhere to go|emergency|disaster|no sewer|not flushing)\b/],
    ]],
  ];

  const routePhrase = text => (normalize(text).replace(/['’]/g, '').match(/[\p{L}\p{N}]+/gu) || []).join(' ');
  const clauseBoundary = /[.!?;,:]+|\b(?:but|however|whereas|except)\b|\band\s+(?=(?:now|today|just|he|she|they|we|i|my|his|her|there|swallowed|ingested|fell|started bleeding|got bitten|got stung)\b)/iu;
  const recentEvent = /\b(?:today|now|just|this (?:morning|afternoon|evening))\b/;
  const historicalEvent = /\b(?:used to|history of|last year|(?:years?|months?) ago|in the past|previously)\b/;
  const absentSymptom = /\b(?:not|no|isnt|arent|wasnt|werent|without|denies|denied) (?:\b(?:really|currently|any|longer|signs? of|evidence of|having|had|have|a|an|the) +)*(?:chok\w*|stroke|seizure\w*|convuls\w*|asthma|fever\w*|bleed\w*|blood|pain|chest (?:pain|pressure|tightness)|trouble breathing|shortness of breath|wheez\w*|cough\w*|dizz\w*|rash|nausea|vomit\w*|headache|injur\w*|burn\w*|(?:heart|asthma) attack|allergic reaction|hives|swelling|faint\w*|unconscious|diarrh\w*|dehydrat\w*|fractur\w*|broken (?:bone|arm|leg)|poison\w*|swallow\w*|bitten|stung|drown\w*)\b/;

  function currentEvents(text) {
    let excluded = false;
    const clauses = text.split(clauseBoundary).flatMap(raw => {
      let phrase = routePhrase(raw);
      const history = historicalEvent.exec(phrase);
      if (history) {
        // An explicit change of time can also open a clause without punctuation.
        const current = recentEvent.exec(phrase.slice(history.index + history[0].length));
        phrase = current ? phrase.slice(history.index + history[0].length + current.index) : '';
        excluded = true;
      }
      const negation = absentSymptom.exec(phrase);
      if (negation) {
        phrase = phrase.slice(0, negation.index).trim();
        excluded = true;
      }
      return phrase ? [phrase] : [];
    });
    return {clauses, phrase: clauses.join(' '), excluded};
  }

  function compileSectionRoutes(rows) {
    const pattern = value => new RegExp('\\b(?:' + value + ')\\b', 'u');
    return rows.map(([topic, title, locations, aliases]) => ({
      topic, title, locations: resolveSectionLocations(locations, title),
      name: routePhrase(title),
      headings: locations.map(([, , heading = title]) => routePhrase(heading)),
      aliases: aliases.map(group => (Array.isArray(group) ? group : [group]).map(pattern)),
    }));
  }

  function resolveSectionLocations(locations, title) {
    return locations.map(([source, locator, heading = title]) => [sectionSources[source], locator, heading]);
  }

  // BEGIN GENERATED EMERGENCY SECTIONS
  const sectionSources = {"home":"hesperian_en_cgeh_2012_17","bec":"medical_bec","cert":"cert","fema":"fema_are_you_ready_2020","grain":"fao_family_metal_silos","produce":"ucdavis_smallscale_postharvest","m08":"hesperian_en_midw_2026_08","m13":"hesperian_en_midw_2026_13","m14":"hesperian_en_midw_2026_14","msf":"msf_guideline-170-en","ob":"msf_guideline-449-en","w10":"hesperian_en_wtnd_2025_10","w13":"hesperian_en_wtnd_2025_13","w15":"hesperian_en_wtnd_2025_15","w16":"hesperian_en_wtnd_2025_16","w22":"hesperian_en_wtnd_2025_22","wiki":"wikimed_en","w12":"hesperian_en_wtnd_2025_12","w18":"hesperian_en_wtnd_2025_18","who-cpr":"who_emergency_medical-algorithm"};
  const sectionRoutes = compileSectionRoutes([
    ["downed-power-line","Downed power lines",[["fema",11,"Power lines and flood hazards"]],["(?:downed|fallen|dangling|live) (?:power lines?|electrical (?:lines?|wires?))",["power (?:lines?|cables?)|electrical (?:lines?|cables?|wires?)|overhead (?:lines?|wires?)","down|fell|fallen|sparks?|sparking|on the ground|across (?:the|our) (?:road|driveway)"]]],
    ["scald","First aid for hot-liquid scalds",[["msf",339,"Burns"]],["scald\\w*",["(?:boiling|hot|scalding) (?:water|tea|coffee|soup|milk|liquid|broth|oil)","spill\\w*|splashed|splas\\w*|pour\\w*|fell (?:on|onto)|dropped on|burn\\w*"],["tea|coffee|soup|broth|stew|hot food","spill\\w*|splash\\w*|pour\\w*","blister\\w*|burn\\w*|scald\\w*"]]],
    ["sunburn","Sunburn and skin care",[["w10",22,"Minor burns"]],["sun ?burn\\w*|sunburnt|sunburned",["in the sun|sun exposure|sunbathing|sunbath\\w*","red|pink|blister\\w*|peel\\w*","skin|shoulders?|back|face|arms?|legs?|pain\\w*|stings?|tender"]]],
    ["long-lie","Emergency assessment after a long time on the floor",[["bec",26,"Emergency assessment and first aid"],["bec",70,"Assessment for injury from prolonged pressure"]],["long lie after a fall",["elderly|older (?:person|adult|man|woman)|grand\\w*|senior|aged (?:man|woman)|pensioner|[7-9]\\d year old","floor|ground","all night|overnight|(?:\\w+ )?hours|long time|since (?:yesterday|last night)|(?:this morning|early today).{0,35}(?:been there|fell)","found|lying|lay|fell|fallen|couldnt get up|could not get up|on (?:the|her|his) (?:floor|ground)"],["found|discovered","lying|lay|fell|fallen|couldnt get up|could not get up","floor|ground","all night|overnight|(?:for |several |many )hours|long time|since (?:yesterday|last night)"]]],
    ["fishhook","Fishhooks and impaled objects",[["cert",110,"Impaled objects"],["w10",15,"Puncture wounds"]],["(?:fish ?hooks?|fishing hooks?) (?:remov\\w*|injur\\w*|first aid)",["fish ?hooks?|fishing hooks?","barb\\w*|stuck|embedded|lodged|remove|pull|went into|skin|finger|thumb"]]],
    ["embedded-object","First aid for embedded objects",[["cert",110,"Impaled objects"]],["(?:impaled|embedded) objects?|object (?:stuck|embedded) (?:in|into) (?:the )?(?:wound|skin)",["glass|metal|wood|shard\\w*|object|knife|piece","embedded|impaled|deeply stuck|lodged in|stuck in the wound"]]],
    ["jellyfish-sting","Jellyfish stings",[["wiki","Jellyfish_stings"]],["jellyfish stings?|marine envenomation",["jellyfish|tentacles?|sea nettle","sting\\w*|stung|welts?|burning|painful (?:stripes|marks)|skin|touched"]]],
    ["tourniquet","Tourniquets for severe limb bleeding",[["bec",170,"Tourniquets for severe bleeding"],["wiki","Tourniquet","Tourniquet"]],["tourniquets?"]],
    ["root-vegetable-storage","Keeping root vegetables after harvest",[["produce",147,"Storage requirements for vegetables"]],["root cellar|root vegetable storage",["root (?:vegetables|crops)|potatoes|turnips|carrots|parsnips|beets","keep\\w*|stor\\w*|preserv\\w*|save","winter|harvest|without (?:a )?(?:fridge|refrigerat\\w*)|no power|lost power|long term"]]],
    ["grain-storage","Storing dried grain",[["grain",94,"Loading and sealing a grain silo"]],["grain storage|stor\\w* (?:dry |dried )?(?:grains?|cereals?)",["grains?|wheat|rice|maize|barley|cereals?","stor\\w*|keep|silos?","dry|dried|flood\\w*|pests?|weevils?|rodents?|long term"]]],
    ["febrile-seizure","Febrile seizures in children",[["msf",23,"Febrile seizures"],["wiki","Febrile_seizure","Febrile seizure"]],["febrile (?:seizures?|convulsions?)|fever convulsions?",["kid|child|toddler|little (?:boy|girl)|preschooler|year old","fever|temperature|burning up|feels? hot","seizure\\w*|convuls\\w*|went stiff|jerk\\w*|shook|eyes? roll\\w*"]]],
    ["cold-water-injury","Cold-water injury and immersion",[["cert",114,"Treating cold-related injuries"],["wiki","Non-freezing_cold_injury","Non-freezing cold injury"]],["cold water (?:injur\\w*|immersion)|non freezing cold injur\\w*",["icy|freezing|cold|frigid","water|river|lake|creek|sea|ocean","numb\\w*|tingl\\w*|prickl\\w*|pins and needles|shiver\\w*"]]],
    ["ice-breakthrough","Fall through ice and cold-water immersion",[["cert",114,"Hypothermia and cold exposure"],["wiki","Drowning","Drowning"],["bec",89,"Breathing assessment after drowning"]],["(?:fell|fallen|went|broke|break\\w*) through (?:\\w+ ){0,3}ice",["ice (?:broke|crack\\w*|gave way|collapsed)|thin ice","through|under|into|fell|sank|went|water"]]],
    ["immersion-foot","Trench foot and immersion foot",[["wiki","Trench_foot"],["cert",114,"Recognizing cold-related injuries"]],["trench foot|immersion foot",["feet|foot|toes","wet (?:boots|socks|shoes)|soaked (?:boots|socks|shoes)","numb\\w*|swell\\w*|swollen|wrinkl\\w*|pain|blisters?"]]],
    ["flood-mold","Mold after flooding",[["wiki","Mold_health_issues"],["home",5,"Ventilation and indoor mold"]],["(?:mold|mould) (?:after|from) (?:a )?flood\\w*",["mold|mould|mildew|musty|fuzzy patches","flood\\w*|storm|water damage|wet walls?|wet drywall|damp basement"]]],
    ["flood-evacuation","Flood evacuation and rising water",[["fema",11,"Flood evacuation and safety"],["fema",12,"If trapped in a building by flooding"]],["flood evacuations?",["river|creek|stream|water\\w*|flood\\w*","ris\\w*|rising|climbing|overflow\\w*|up to|banks|approach\\w*|coming closer","evacuat\\w*|leave|when to go|higher ground|house|home|back steps|door"]]],
    ["penetrating-wound","Bullet, knife, and other serious wounds",[["w10",16]],["gunshot wounds?|bullet wounds?|stab wounds?",["shot|stabbed","bleed\\w*|wound|hurt"],"knifed|stabbed|stab wound|knife went into",["blade|knife|shard|spike|glass|metal","abdomen|belly|gut|chest|side|ribs","deep|pierc\\w*|went (?:in|into|through)|hole|punctur\\w*"]]],
    ["gastrointestinal-bleeding","Gastrointestinal bleeding and vomiting blood",[["msf",122,"Gastrointestinal bleeding"],["bec",107,"Blood in stool or vomit"]],[["coffee grounds","vomit\\w*|threw up|throw\\w* up"],"gastrointestinal bleeding|h(?:a)?ematemesis|vomit\\w* blood|bloody vomit|threw up blood|black tarry stools?","throw(?:ing|s)? up blood|puk\\w* blood|blood (?:in|mixed with) (?:the |his |her |my )?vomit",["black|tar\\w*|maroon","stools?|poop|bowel movement"]]],
    ["stroke-signs","Stroke and sudden weakness",[["bec",139,"Stroke"],["bec",147,"Stroke management"],["w22",5,"Stroke"]],[["left arm|right arm|one arm|left side|right side|one side","heavy|weak\\w*|numb\\w*|cant lift|wont move","cant say|cant get (?:the )?words|cant speak|cant talk|speech|slurr\\w*"],["face|smile|grin|mouth","droop\\w*|sagg?\\w*|crooked|uneven|lopsided","sudden\\w*|speech|speak\\w*|say\\w*|arm|hand"],["arm|hand|leg|one side","weak\\w*|numb\\w*|cant lift|wont move|dropp\\w*","face|smile|grin|mouth|slurr\\w*|speech"]]],
    ["injury-to-eye","Eye injuries",[["w16",2,"Injuries to the eye"]],["eye injur\\w*|injur\\w* to (?:the )?eye|corneal abrasion|scratched cornea",["eye|eyeball","poked|scratched|cut|hit","vision|pain|bleed\\w*|blood"],["eyes?|eyeball","branch|twig|stick|hook|projectile","hit|struck|poke\\w*|snap\\w*|whip\\w*|blurr\\w*"]]],
    ["fire-smoke","House fire and indoor smoke",[["cert",173,"Fire suppression safety rules"],["cert",30,"Escape planning"]],["home fire safety|residential fire safety",["smok\\w*|burn(?:t|ing) smell|smells? (?:burnt|like smoke)","inside|walls?|ceilings?|hallway|apartment|house|indoors"],["smoke alarms?|smoke detectors?","going off|sound\\w*|went off|smell|visible"]]],
    ["newborn-resuscitation","Newborn resuscitation and breathing",[["m13",20,"Breathing"],["ob",217,"Neonatal resuscitation"]],["(?:newborn|neonatal) resuscitation",["newborn|neonatal|baby","baby came out|baby was (?:just )?born|just (?:been )?born|after birth|newborn|neonatal","(?:hasnt|has not) (?:taken|started)|not breathing|wont breathe|isnt breathing|no breaths?|stopped breathing|never (?:cried|breathed)"]]],
    ["newborn-warmth","Keeping a newborn warm",[["m14",10,"Keep the baby warm"],["m13",19,"Keep the baby warm and dry"]],[["newborn|new baby|just born|neonat\\w*|premature baby|infant|baby","cold to the touch|feels? cold|body (?:is )?cold|keep\\w* (?:\\w{1,} ){0,5}warm|hypotherm\\w*|no heater"]]],
    ["newborn-jaundice","Newborn jaundice",[["ob",224,"Jaundice"],["m14",21,"If the baby looks yellow"]],[["newborns?|baby|neonatal","yellow\\w*|jaundice|hyperbilirubin\\w*"]]],
    ["newborn-seizure","Newborn seizures",[["ob",225,"Seizures"]],[["newborn|neonat\\w*","seizure\\w*|convuls\\w*|jerk\\w*|twitch\\w*"]]],
    ["preeclampsia","Pre-eclampsia and eclampsia",[["m08",18,"Check for signs of pre-eclampsia"],["ob",69,"Management of pre-eclampsia with severe features"]],["pre ?eclampsia|eclampsia|toxemia of pregnancy",["pregnan\\w*|(?:[5-9]|five|six|seven|eight|nine) months? along","headache\\w*|seizure\\w*|convuls\\w*","flash\\w*|vision|spots|blur\\w*|blood pressure"]]],
    ["ectopic-pregnancy","Ectopic pregnancy",[["ob",32]],["ectopic pregnancy|tubal pregnancy",["pregnan\\w*|missed (?:her|my) period","one sided (?:belly|abdominal|pelvic) pain|shoulder tip pain","bleed\\w*"]]],
    ["bleeding-during-pregnancy","Vaginal bleeding during pregnancy",[["m08",5,"Ask if she has any bleeding from the vagina"],["ob",39,"Bleeding during the second half of pregnancy"]],["antepartum h(?:a)?emorrhag\\w*|bleeding (?:in|during) pregnancy|bleeding before birth",["pregnan\\w*","vaginal bleed\\w*|vagina (?:is )?bleed\\w*|spotting blood"],["pregnan\\w*","bleed\\w*","too early|not due|before (?:labor|labour|birth)|weeks? along"]]],
    ["placenta-praevia","Placenta previa and bleeding",[["ob",40,"Placenta praevia"]],["placenta pr(?:ae|e)via|placenta covering (?:the )?cervix"]],
    ["placental-abruption","Placental abruption",[["ob",43,"Abruptio placentae"]],["placental abruption|abruptio placentae|placenta (?:came|is coming) away early"]],
    ["retained-placenta","Retained placenta",[["ob",179],["m13",6,"Help the mother push out the placenta"]],["retain\\w* placenta",["placenta|afterbirth","still inside|not (?:come|coming|out)|wont come|stuck|hasnt come|didnt come"]]],
    ["placenta-delivery","Delivery of the placenta",[["m13",2,"The birth of the placenta"],["ob",172,"Normal third stage of labour"]],["placenta delivery|delivery of (?:the )?placenta|third stage of labo[u]?r"]],
    ["shoulder-dystocia","Shoulder dystocia",[["ob",154]],["shoulder dystocia",["baby|childbirth","head (?:is )?out|head (?:was|has been) delivered","shoulders?|stuck|wont come"]]],
    ["breech","Breech birth",[["ob",122,"Breech presentation"]],["breech (?:birth|presentation|baby|delivery)|baby (?:is )?coming (?:feet|bottom) first"]],
    ["rupture-membranes","Early rupture of membranes",[["ob",77,"Premature rupture of membranes"]],["(?:premature|prelabor|prelabour) rupture of membranes",["water broke|waters broke","no contractions|not due|too early|preterm"]]],
    ["preterm-delivery","Preterm delivery",[["ob",81]],["premature labo[u]?r|preterm (?:delivery|labo[u]?r)|contractions too early"]],
    ["uterine-rupture","Uterine rupture",[["ob",46]],["uterine rupture|ruptured uterus"]],
    ["newborn-infection","Danger signs and infection in newborns",[["ob",220,"Danger signs"],["ob",222,"Neonatal infection"]],["neonatal (?:sepsis|infection)|newborn (?:danger signs|infection|sepsis)",["newborn|days old","too sleepy to feed|not feeding|wont feed|wont nurse","fever|very cold|limp"]]],
    ["newborn-low-sugar","Low blood sugar in newborns",[["ob",223,"Hypoglycaemia"]],[["newborn|neonat\\w*","low blood (?:sugar|glucose)|hypoglyc\\w*"]]],
    ["postpartum-infection","Infection after birth",[["ob",242,"Infectious complications"]],["postpartum infection|puerperal sepsis|postpartum endometritis",["gave birth|after delivery|after (?:giving )?birth","fever|chills","pelvic pain|smelly discharge|foul discharge"]]],
    ["late-postpartum-bleeding","Late bleeding after birth",[["ob",181,"Late postpartum haemorrhage"]],["late postpartum (?:bleeding|h(?:a)?emorrhage)",["bleed\\w*","weeks? after (?:giving )?birth|weeks? since (?:giving )?birth"]]],
    ["opioid-overdose","Opioid overdose",[["bec",96],["bec",234,"Critical actions for high-risk conditions"]],["opioid overdose|opiate overdose|heroin overdose|naloxone|narcan",["heroin|opioids?|fentanyl|pain pills","overdos\\w*|barely breathing|wont wake|slow breathing"]]],
    ["spinal-injury","Spinal cord and neck injuries",[["bec",67,"Spinal cord injury"],["cert",131,"Closed-head, neck, and spinal injuries"],["w10",25,"Broken necks and backs"]],["spinal (?:cord )?injur\\w*|broken neck|broken spine|broken back|cervical spine injur\\w*",["neck|spine|back","fall|fell|crash\\w*|wreck|collision|got hit|accident|rear ended","neck (?:really )?(?:hurts?|pain)|numb\\w*|tingl\\w*|cant move"]]],
    ["head-injury","Head injury and concussion",[["bec",65,"Head injury"],["cert",131,"Closed-head, neck, and spinal injuries"]],["head injur\\w*|concussion\\w*|brain injur\\w*",["hit|struck|knock\\w*|bang\\w*|blow to","head|skull","throw\\w* up|vomit\\w*|fall|fell|confus\\w*|cant remember|keeps asking|pass\\w* out|dizz\\w*|severe headache"]]],
    ["amputation","First aid for amputations",[["cert",109,"Amputations"]],["amputat\\w*|severed (?:finger|thumb|toe|hand|arm|foot|limb)",["finger|thumb|toe|hand|foot|arm|leg","cut (?:right |clean )?off|took .{0,28} (?:clean |right )?off|chopped .{0,20}off|sliced .{0,20}off"]]],
    ["crush-injury","Crush injury",[["bec",70],["wiki","Crush_syndrome","Crush syndrome"]],["crush injur\\w*|crush syndrome|crushed limb",["leg|arm|body|limb|hand|wrist|fingers?|thumb|toes?|foot|feet|person","trapped under|pinned under|pinned .{0,25}against|crushed under|crushed by|squash\\w* by|beam fell|rock fell|ran over|rolled over"],["leg|arm|limb|hand|fingers?|thumb|toes?|foot|feet","caught|jammed|crush\\w*|squash\\w*|pinch\\w*|pull\\w*|wedg\\w*|trapped|shut|slam\\w*|closed|came down","door|tailgate|press|rollers?|machin\\w*|conveyor|lathe|gears?"]]],
    ["entrapment","Entrapment and rescue scene safety",[["cert",192,"Deciding whether a rescue is safe"],["bec",70,"Assessment for crush injury"]],["(?:person|survivor|driver|passenger) (?:is )?(?:trapped|pinned)|(?:vehicle|structural) entrapment",["trapped|pinned|wedged|stuck|cannot get out|cant get out|unable to get out","(?:under|underneath|beneath) (?:\\w+ ){0,4}(?:rubble|debris|bookcase|cabinet|beam|wall|roof|ceiling|tree|branch|boulder|furniture|tractor|fell|fallen)"],["trapped|pinned|wedged|stuck|cannot get out|cant get out|unable to get out","passenger|driver|wreck|crash\\w*|collision|overturned|rolled over","car|truck|van|vehicle|cab|seat belt|seatbelt|doors?"]]],
    ["nosebleed","How to stop nosebleeds",[["w10",9]],["nose ?bleeds?|epistaxis|bleeding from (?:the |his |her |my |their )?nose|nose (?:is |started )?bleed\\w*",["blood|bleed\\w*","from (?:one |a |the |his |her |my |their )?(?:nose|nostril)|out of (?:one |a |the |his |her |my |their )?(?:nose|nostril)"]]],
    ["object-in-eye","Foreign body in the eye",[["w16",2,"How to remove a speck of dirt from the eye"]],["foreign bod\\w* in (?:the )?eye|something (?:stuck )?in (?:my |his |her |the )?eye",["speck|grit|dust|sawdust|metal shaving|debris","eye|blink\\w*"],["eye|blink\\w*","flew (?:into|under)|got into","speck|sand|dirt|glasses|grit|particle"]]],
    ["acute-glaucoma","Acute glaucoma",[["w16",6]],["acute glaucoma|acute angle closure glaucoma",["eye pain","blurred vision|halos around lights","nausea|vomit\\w*"]]],
    ["tick-bite","Tick bites and tick removal",[["w15",9,"Ticks and chiggers"]],["tick bite\\w*|bitten by (?:a |the )?tick|remove (?:a |the )?tick",["ticks?","attach\\w*|embed\\w*|stuck|skin|bite\\w*|bitten|bit|pull|remov\\w*|get .{0,12}off"]]],
    ["scorpion-sting","Scorpion stings",[["w10",32,"Scorpion sting"],["msf",357,"Scorpion stings and envenomation"]],[["scorpion\\w*","sting\\w*|stung|bit\\w*|got me|hurts?"]]],
    ["spider-bite","Spider bites",[["w10",32,"Black widow and other spider bites"],["msf",357,"Spider bites and envenomation"]],["spider bites?|black widow bite|brown recluse bite",["spiders?","bites?|bit|bitten|skin|swoll\\w*|pain"],["spiders?","marks?","arm|hand|leg|redder"]]],
    ["lizard-bite","Beaded lizard and Gila monster bites",[["w10",32,"Bite of the beaded lizard"]],[["(?:gila monster|beaded lizard)","bit\\w*|venom"]]],
    ["sprain","Sprains and strains",[["cert",110,"Treating fractures, dislocations, sprains, and strains"],["w10",28,"Strains and sprains"]],["sprains?|muscle strain",["ankle|joint","twist\\w*|roll\\w*|slip\\w*","swell\\w*|swoll\\w*|hurts?|pain"]]],
    ["dislocation","Dislocations",[["w10",27],["cert",110,"Treating fractures, dislocations, sprains, and strains"]],["dislocat\\w*|shoulder came out|kneecap popped out",["kneecap|shoulder|elbow|joint","slid off|popped out|out of place|came out of (?:its )?socket"]]],
    ["hip-fracture","Hip fractures and broken hip bones",[["w10",25,"Broken thigh or hip bone"]],["hip fractures?|broken hip",["hip|groin","fell|fallen|tumbled|fall|slipp\\w*","hurts?|pain|cant stand|cannot stand|cant walk|cannot walk"]]],
    ["wrist-fracture","Broken wrist and wrist fractures",[["w10",24,"How to set a broken wrist"]],["broken wrist|wrist fracture",["wrist","bent (?:the )?wrong way|crooked|at (?:an? )?(?:odd|unnatural) angle"]]],
    ["fall-from-height","Injury after a fall from height",[["bec",58,"Falls and other high-risk injuries"],["w10",26,"How to move a badly injured person"]],["falls? from (?:a )?(?:height|roof|ladder)|high falls?",["fell|fallen|fall|dropped|came off|tumbled|plung\\w*","roof|ladder|scaffold\\w*|balcony|stories|storeys|cliff|overpass","ground|landed|concrete|driveway|not moving|pain|hurt|injur\\w*|fell|fallen"]]],
    ["rib-fracture","Broken ribs and rib fractures",[["w10",25,"Broken ribs"]],["broken ribs?|rib fracture\\w*"]],
    ["open-fracture","Open fractures",[["w10",25,"Broken bones that break through the skin"],["cert",110,"Treating fractures, dislocations, sprains, and strains"]],["open fracture\\w*|compound fracture\\w*|bone (?:is )?(?:sticking|poking) (?:out|through)"]],
    ["splinting","Splinting fractures and injuries",[["cert",112,"Splinting"]],["splint (?:a |the )?(?:broken|injured)|splinting|improvis\\w* splint"]],
    ["appendicitis","Appendicitis and peritonitis",[["w10",20,"Appendicitis, peritonitis"]],["appendicit\\w*|peritonitis",["right side|on the right|lower right","belly|abdom\\w*|stomach","hurt\\w*|pain|tender\\w*"]]],
    ["acute-abdomen","Severe abdominal pain and the acute abdomen",[["w10",19,"Emergency problems of the gut"]],["acute abdomen|severe (?:abdominal|belly) pain",["belly|abdom\\w*|stomach","rock hard|hard as a board|rigid","pain|hurts"]]],
    ["seizure","Seizures and convulsions",[["msf",22,"First aid during a seizure"],["bec",139]],["seizure\\w*|convuls\\w*|epileptic fit|epilepsy","shaking all over|body (?:went|got) stiff",["jerk\\w*|twitch\\w*","eyes? roll\\w*|unresponsive|foaming|went stiff|cant wake"]]],
    ["asthma-attack","Acute asthma attack",[["msf",104,"Acute asthma (asthma attack)"],["bec",97,"Asthma and COPD"]],["asthma attacks?|asthma exacerbation|bronchospasm|rescue inhaler",["asthma\\w*|puffer|inhaler","wheez\\w*|breath\\w*|isnt (?:doing|helping|working)|not (?:helping|working)|cant (?:get air|talk)|didnt help"]]],
    ["low-blood-sugar","Low blood sugar (hypoglycaemia)",[["msf",32,"Hypoglycaemia"],["bec",137,"Hypoglycaemia"]],["hypoglyc\\w*|low blood (?:sugar|glucose)|insulin shock",["diabet\\w*|insulin","shak\\w*|sweat\\w*|confus\\w*|missed (?:a meal|lunch)|skipped (?:lunch|food|dinner|breakfast)"]]],
    ["pneumonia","Pneumonia and difficulty breathing",[["bec",94,"Pneumonia"],["msf",98,"Pneumonia in children over five years and adults"],["w13",21,"Pneumonia"]],["pneumonia|lower respiratory tract infection",["fever|high temperature","cough\\w*","breathing (?:hard|fast)|short of breath|struggl\\w* to breathe|blue lips|gray lips|grey lips"]]],
    ["meningitis","Meningitis",[["msf",219]],["meningit\\w*",["fever|high temperature","stiff neck|neck (?:is )?stiff","headache|light hurts|rash"]]],
    ["shock","Recognizing shock",[["w10",3,"Shock"],["msf",11,"Shock"],["bec",54,"Hypovolaemic shock"]],["medical shock|hypovol(?:ae|e)mic shock|circulatory shock|(?:signs|symptoms) of shock",["clammy|cold sweat\\w*","pale|ashen","fast pulse|pulse .{0,20}fast|weak pulse|feel faint"]]],
    ["tension-pneumothorax","Pneumothorax and chest injury",[["bec",31,"Tension pneumothorax"]],["pneumothorax|punctured lung|collapsed lung"]],
    ["dangerous-wounds","Deep and contaminated wounds",[["w10",15,"Wounds that are likely to become dangerously infected"]],["deep contaminated wounds?|dirty deep cuts?"]],
    ["wound-infection","Recognizing infected wounds",[["w10",14,"Infected wounds"],["cert",109,"Wound care"]],["infected (?:wounds?|cuts?)|wound infection",["cut|wound|scrape","pus|spreading redness|red streak\\w*|festering"]]],
    ["small-wounds","First aid for cuts, scrapes, and small wounds",[["w10",10,"Cuts, scrapes, and small wounds"],["cert",109,"Wound care"]],["small wounds?|minor cuts?|clean (?:a |the )?(?:cut|scrape)|grazed (?:knee|elbow)"]],
    ["large-cuts","Large cuts and wound closure",[["w10",11,"Large cuts: how to close them"]],["wound closure|butterfly bandage\\w*",["cut|wound","gaping|edges wont meet|needs? stitches"]]],
    ["dressings","Bandages and dressings",[["w10",13,"Bandages"],["cert",109,"Wound care"]],["wound dressing|bandage (?:a |the )?wound|bandag\\w* (?:an? )?injur\\w*"]],
    ["impaled-object","Impaled objects",[["cert",110]],["impaled (?:object|person|limb)|impalement",["object|knife|metal rod|glass","still stuck in|sticking out of","body|skin|leg|arm|chest|belly"]]],
    ["infection-protection","Protecting yourself while providing first aid",[["w10",1,"Basic cleanliness and protection"],["cert",128,"Safety for rescuers and survivors"]],["first aid gloves|bloodborne (?:infection|exposure)|protect .{0,22}from blood"]],
    ["first-aid-assessment","Emergency assessment and first aid",[["cert",100,"Treating life-threatening conditions"],["bec",26,"The ABCDE assessment and management"]],["abcde (?:approach|assessment)|primary survey first aid|life threatening condition\\w*"]],
    ["recovery-position","Recovery position",[["cert",106],["bec",139,"Seizures and recovery position"]],["recovery position|side lying position first aid"]],
    ["opening-airway","Opening the airway",[["cert",104],["bec",29,"Airway conditions"]],["open (?:the )?airway|opening the airway|jaw thrust|head tilt chin lift"]],
    ["patient-warmth","Keeping an injured person warm",[["cert",103,"Maintaining body temperature"]],[["injur\\w*|shock","keep .{0,20}warm|warm (?:the )?patient"]]],
    ["patient-movement","Moving a badly injured person",[["w10",26,"How to move a badly injured person"]],["mov\\w* (?:a |an |the )?(?:badly )?injur\\w* (?:person|patient)|carry (?:an? )?injured person"]],
    ["head-to-toe","Head-to-toe injury assessment",[["cert",130,"Conducting head-to-toe assessments"]],["head to toe (?:injury )?(?:check|assessment)|secondary survey trauma"]],
    ["trauma","Emergency care for trauma",[["bec",48,"Approach to trauma"],["cert",107,"Basic first-aid care"]],["serious injur\\w*|major trauma|multiple injur\\w*|trauma first aid"]],
    ["vomiting","Vomiting",[["w13",11]],["frequent vomit\\w*|vomiting first aid|throwing up repeatedly"]],
    ["fever","Fever first aid",[["w10",1,"Fever"],["msf",34,"Fever"]],["fever first aid|(?:really high|very high) fever|what to do (?:about|for) (?:a )?fever"]],
    ["ear-infection","Ear infections",[["msf",82,"Acute otitis media"]],["ear infection\\w*|otitis media",["earache|ear pain","fever|pus"]]],
    ["skin-abscess","Boils and skin abscesses",[["w15",10,"Boils and abscesses"]],["skin abscess\\w*|infected boil|painful boil|boil on (?:the |my )?skin"]],
    ["wildfire","Wildfire safety and evacuation",[["fema",15,"Wildfire"]],["wildfires?|wildland fires?|brush fires?|forest fire\\w*"]],
    ["tornado","Tornado safety and shelter",[["fema",14,"Tornado"]],["tornad\\w* (?:warn\\w*|shelter|sirens?|coming|nearby)|twisters? (?:is |are )?(?:coming|heading|approach\\w*)|tornado sirens?"]],
    ["tsunami","Tsunami warning and safety",[["fema",14,"Tsunami"]],["tsunamis?",["ocean|sea","pulled back|pulled way back|receded|receding|went out suddenly","shak\\w*|quake|earthquake"]]],
    ["landslide","Landslide and debris flow safety",[["fema",12,"Landslide"]],["landslides?|mudslides?|debris flow",["hill\\w*|slope|mountainside","sliding down|giving way|collaps\\w*","rain|house|road"]]],
    ["lightning","Lightning and thunderstorm safety",[["fema",13,"Thunderstorm, lightning, and hail"]],["lightning (?:strike|strikes|storm|safety)|thunderstorm\\w* (?:warn\\w*|shelter|approach\\w*|coming)",["thunder|lightning","open field|outside|getting closer|nowhere to shelter"]]],
    ["hurricane","Hurricane and storm surge safety",[["fema",11,"Hurricane"]],["hurricanes?|storm surges?|tropical cyclones?"]],
    ["winter-storm","Winter storm safety",[["fema",15,"Winter storm"]],["winter storm\\w*|blizzard\\w*|whiteout\\w*|ice storm\\w*"]],
    ["volcano","Volcano and ashfall safety",[["fema",14,"Volcano"]],["volcanic eruption\\w*|ashfall|volcano (?:is )?erupt\\w*"]],
    ["avalanche","Avalanche safety",[["fema",9,"Avalanche"]],[["avalanches?|snow slide","buried|trapped"]]],
    ["evacuation","Evacuation and shelter plans",[["fema",17,"Make an evacuation and shelter plan"]],["evacuation (?:order|plan|route)|ordered to evacuate|forced to evacuate|shelter in place"]],
    ["disaster-shelter","Basic protective actions in a disaster",[["fema",8,"Basic protective actions for all disasters"],["fema",17,"Make an evacuation and shelter plan"]],["disaster shelter|storm shelter|public emergency shelter"]],
    ["emergency-alerts","Emergency alerts and warnings",[["fema",20,"Keep informed: alerts and warnings"]],["emergency alerts?|weather alerts?|disaster warnings?|alert siren\\w*"]],
    ["emergency-supplies","Gathering emergency supplies",[["fema",18,"Gather emergency supplies"]],["emergency (?:kit|supplies)|disaster supplies|go bag|bug out bag"]],
    ["family-plan","Family emergency communication plan",[["fema",16,"Create a family emergency communication plan"],["cert",24,"Family disaster plan"]],["family (?:disaster|emergency) plan|emergency communication plan|emergency meeting place"]],
    ["disaster-recovery","Returning home after a disaster",[["fema",25,"Recovering from a disaster"],["fema",26,"Before you enter your home"]],["return\\w* home after (?:a |the )?disaster|is it safe to go back home after"]],
    ["hazardous-spill","Hazardous materials and chemical spills",[["cert",179,"Hazardous materials"]],["hazmat|hazardous materials spill|chemical spill|tanker (?:is )?leaking"]],
    ["fire-extinguisher","Fire extinguishers and small fires",[["cert",168,"Fire extinguishers"],["cert",170,"Deciding to use a fire extinguisher"]],["fire extinguishers?|put out (?:a |the )?small fire"]],
    ["mass-casualty","Mass casualty incidents",[["cert",125]],["mass casualty|mass injury incident|disaster triage"]],
    ["heating-outage","Power outage safety",[["fema",13,"Power outage"]],["power outage safety|blackout safety"]],
    ["anaphylaxis-signs","Anaphylaxis and severe allergic reactions",[["msf",14,"Anaphylaxis"],["cert",116,"Allergic reactions to bites and stings"]],[["bee|wasp|hornet|sting\\w*|peanuts?|allergen|allerg\\w*","hoarse|voice (?:changed|is changing)|stridor|hives","swoll\\w*|puff\\w*|breath\\w*|hives"],["bee|wasp|sting\\w*","swoll\\w*|puff\\w*|hives","face|lips?|tongue","hoarse|breath\\w*|throat"]]],
    ["electric-injury","Electrical injury",[["cert",175,"Responding to electrical emergencies"]],[["jolt|shock\\w*","touch\\w*|grab\\w*","plug|appliance|washing machine|dryer|metal case|power tool"]]],
    ["poison-ingestion","Poisoning and accidental ingestion",[["w10",29,"Poisoning"]],[["drank|swallow\\w*|took a sip","unmarked (?:bottle|container)|unknown liquid|chemical bottle","mouth|throat|burn\\w*|sick|vomit\\w*"]]],
    ["food-safety","Food safety and contaminated food",[["w12",5,"Food and drink cleanliness"]],["food safety|food poisoning|foodborne illness|spoiled food",["safe to eat|safe to cook|still good|throw (?:it|them) out","meat|fish|chicken|leftovers?|food|milk|eggs?","room temperature|left out|thaw\\w*|too warm|warm overnight|smell\\w*|expired"]]],
    ["breathing-difficulty","Difficulty breathing",[["bec",86,"Approach to difficulty in breathing"]],["difficulty (?:in )?breathing|shortness of breath|respiratory distress"]],
    ["altered-mental-status","Sudden confusion and altered mental status",[["bec",129,"Approach to altered mental status"]],["altered mental status|person suddenly confused|sudden confusion"]],
    ["smoke-inhalation","Smoke inhalation and airway burns",[["bec",91,"Early signs of smoke inhalation"],["bec",229]],["smoke inhalation|inhaled smoke|airway burns"]],
    ["childhood-pneumonia","Pneumonia in young children",[["msf",95,"Pneumonia in children under five years of age"]],["pneumonia in (?:babies|toddlers|young children)|childhood pneumonia"]],
    ["diarrhea-disentery","Diarrhea and dysentery",[["w13",3],["msf",114,"Acute diarrhoea"]],["dysenter\\w*|blood\\w* (?:diarrh\\w*|stool)|diarrh\\w* with blood"]],
    ["prolapsed-cord","Umbilical cord prolapse",[["ob",100,"Prolapsed cord"]],["cord prolapse|prolapsed (?:umbilical )?cord",["pregnan\\w*|labo[u]?r|contractions","cord (?:is )?(?:coming|hanging) out"]]],
    ["severe-fever-pregnancy","Fever during pregnancy",[["m08",12,"Check the mother\u2019s temperature"]],["fever (?:while pregnant|in pregnancy|during pregnancy)",["pregnan\\w*","high fever|fever and chills"]]],
    ["postpartum-mental-health","Severe mood changes after birth",[["ob",245,"Psychological disorders"]],["postpartum (?:depression|psychosis)|postnatal (?:depression|psychosis)"]],
    ["newborn-care","First care for a newborn",[["ob",210,"In the first hours of life"],["m14",11,"Danger signs in a newborn"]],["newborn care|newborn first hours|care of (?:a |the )?newborn"]],
    ["nuclear-emergency","Nuclear emergency shelter",[["fema",12,"Nuclear explosion"]],["nuclear (?:emergency|fallout|explosion)|radioactive fallout"]],
    ["shooter-safety","Active shooter safety",[["fema",9,"Active shooter"]],["active shooter",["someone (?:is )?shooting","shelter|hide|escape"]]],
    ["cyber-safety","Cyberattack preparedness",[["fema",9,"Cyberattack"]],["cyberattack (?:preparedness|safety)|protect (?:against|from) cyberattacks"]],
    ["pandemic","Pandemic preparedness",[["fema",13,"Pandemics"]],["pandemic preparedness|pandemic safety"]],
    ["extreme-heat","Extreme heat safety",[["fema",10,"Extreme heat"],["cert",115,"Treating heat-related injuries"],["w10",7,"Emergencies caused by heat"]],["extreme heat safety|heat related injuries"]],
    ["cold-injury","Cold-related injuries",[["cert",114,"Treating cold-related injuries"]],["cold related injur\\w*|cold weather injur\\w*"]],
    ["disaster-reaction","Stress and emotional responses after a disaster",[["cert",144,"Disaster reactions"],["cert",150,"Working with survivors emotional responses"]],["disaster stress|traumatic stress after a disaster|emotional responses after a disaster"]],
    ["outdoor-rescue","Light search and rescue",[["cert",185,"Light search and rescue operations"]],["light search and rescue|rescue (?:a |the )?trapped person"]],
    ["urinary-retention","Acute urinary retention",[["wiki","Urinary_retention"],["w18",7,"When a person cannot urinate"]],["urinary retention",["(?:cant|cannot|unable to) (?:pee|urinate|pass (?:any )?urine)","bladder|belly|abdom\\w*|urge|desperate|full"]]],
    ["testicular-torsion","Testicular torsion",[["wiki","Testicular_torsion"]],["testicular torsion"]],
    ["diabetic-ketoacidosis","Diabetic ketoacidosis",[["bec",96],["wiki","Diabetic_ketoacidosis"]],["ketoacidosis|dka"]],
    ["sepsis","Sepsis and septic shock",[["msf",14,"Septic shock"],["wiki","Sepsis"]],["sepsis|septic shock"]],
    ["hemoptysis","Coughing up blood (hemoptysis)",[["wiki","Hemoptysis"],["bec",86,"Assessing difficulty breathing"]],["h(?:a)?emoptysis|cough\\w* up blood"]],
    ["compartment-syndrome","Compartment syndrome",[["bec",70],["wiki","Compartment_syndrome"]],["compartment syndrome",["cast|plaster|splint","fingers?|toes?|hand|foot","numb\\w*|tingl\\w*|pale|turn\\w* blue","wors\\w*|pain|hurt\\w*"]]],
    ["croup","Croup",[["msf",76],["wiki","Croup"]],["croup"]],
    ["retinal-detachment","Retinal detachment",[["wiki","Retinal_detachment"],["w16",11,"Sudden floaters and detached retina"]],["retinal detachment|detached retina",["eyes?|vision|sight","dark curtain|gray curtain|grey curtain","flash\\w*|floaters?|(?:cant|cannot) see|one side"]]],
    ["septic-arthritis","Septic arthritis",[["wiki","Septic_arthritis"],["msf",145,"Urgent referral for complications of cellulitis"]],["septic arthritis",["joint|knee|elbow|ankle|hip|wrist","fever|febrile","hot|warm|burning","swoll\\w*|swell\\w*|huge|puffy","weight|walk|bend|move|pain"]]],
    ["deep-vein-thrombosis","Deep vein thrombosis",[["wiki","Deep_vein_thrombosis"],["msf",12,"Signs of deep vein thrombosis and pulmonary embolism"]],["deep vein thrombosis|dvt"]],
    ["pulmonary-embolism","Pulmonary embolism",[["bec",88],["wiki","Pulmonary_embolism"]],["pulmonary embol\\w*",["after surgery|recent surgery|after the operation|been (?:in bed|immobile)|known blood clot","sudden\\w*|all of a sudden|all at once","breathless|short of breath|cant (?:catch|get) (?:her |his |my |their )?breath|cant breathe"]]],
    ["altitude-pulmonary-edema","High-altitude pulmonary edema",[["wiki","High-altitude_pulmonary_edema"]],["high altitude pulmonary (?:o)?edema"]],
    ["rhabdomyolysis","Rhabdomyolysis",[["wiki","Rhabdomyolysis"],["bec",70,"Dark urine after a crush injury"]],["rhabdomyolysis"]],
    ["bowel-obstruction","Bowel obstruction",[["wiki","Bowel_obstruction"],["w10",20,"Obstructed gut"]],["(?:bowel|intestinal) obstruction",["vomit\\w*|puk\\w*|throw\\w* up","bloated|distend\\w*|belly (?:is )?blown up|swollen (?:abdomen|belly)","pass (?:gas|wind|stool)|bowel movements?"]]],
    ["cellulitis","Cellulitis",[["msf",145,"Erysipelas and cellulitis"],["wiki","Cellulitis"]],["cellulitis"]],
    ["botulism","Botulism",[["wiki","Botulism"],["w12",5,"Preventing poisoning from unsafe canned food"]],["botulism"]],
    ["dengue","Dengue fever",[["msf",268,"Dengue"],["wiki","Dengue_fever"]],["dengue"]],
    ["malaria","Malaria",[["msf",181],["wiki","Malaria"]],["malaria"]],
    ["sudden-hearing-loss","Sudden hearing loss",[["wiki","Hearing_loss"]],["sudden hearing loss|sudden deafness"]],
    ["angioedema","Angioedema and sudden swelling",[["wiki","Angioedema"],["msf",14,"Anaphylaxis and airway swelling"]],["angio(?:o)?edema"]],
    ["ovarian-torsion","Ovarian torsion",[["wiki","Ovarian_torsion"],["w10",19,"Emergency assessment for severe abdominal pain"]],["(?:ovarian|adnexal) torsion"]],
  ]);
  const reviewedCompanions = new Map([
    ["carbon-monoxide",[["cert",176,"Carbon monoxide hazards"]]],
    ["chemical-eye",[["w16",3,"Chemical burns of the eye"]]],
    ["electric-shock",[["cert",175,"Responding to electrical emergencies"]]],
    ["drowning",[["bec",89,"Breathing assessment after drowning"]]],
    ["resuscitation",[["who-cpr",1,"Medical resuscitation algorithm"]]],
    ["swallowed-object",[["bec",26,"Emergency assessment and airway danger signs"]]],
    ["ingestion",[["w10",29,"Poisoning"]]],
    ["insect-sting",[["cert",116,"Insect bites and stings"]]],
  ].map(([topic, locations]) =>
    [topic, resolveSectionLocations(locations)]));
  // END GENERATED EMERGENCY SECTIONS

  function guideAt(documents, categoryIds, topic, title, id, locator) {
    const guide = documents.get(id);
    if (!guide || categoryIds && !categoryIds.has(id)) return;
    if (typeof locator === 'number' && /\.pdf$/i.test(guide.href)) {
      return {...guide, topic, title, description: '', kind: 'section',
        href: guide.href + '#page=' + locator, location: 'Page ' + locator};
    }
    if (typeof locator === 'string' && id === 'wikimed_en' && isArchive(guide)) {
      return {...guide, topic, title, description: '', kind: 'article',
        archivePath: locator, articleTitle: locator.replace(/_/g, ' '), location: 'Archive path: ' + locator};
    }
  }

  const locationsByTopic = new Map(reviewedRoutes.map(([topic, title, id, locator]) =>
    [topic, [[id, locator, title], ...(reviewedCompanions.get(topic) || [])]]));
  for (const {topic, title, locations} of sectionRoutes) {
    locationsByTopic.set(topic, locations.map(([id, locator, heading], index) =>
      [id, locator, index ? heading : title]));
  }

  function guidesAt(documents, categoryIds, topic, locations) {
    const guides = locations.map(([id, locator, title]) =>
      guideAt(documents, categoryIds, topic, title, id, locator)).filter(Boolean);
    if (guides.some(isArchive) && !guides.some(guide => guide.kind === 'section')) {
      // A scoped archive result can still use its companion from the drive.
      const pdf = locations.find(([id, locator]) => typeof locator === 'number' && documents.has(id));
      if (pdf) {
        const [id, locator, title] = pdf;
        const guide = guideAt(documents, undefined, topic, title, id, locator);
        if (guide) guides.push(guide);
      }
    }
    return guides;
  }

  const recognitionFloor = 0.48;
  const nearbyFloor = 0.42;
  const emergencyReference = /\b(?:book about|audiobook|life cycle|four stroke engine|flood fill|choke valve|carburetor choke)\b|^(?:(?:how to )?prevent(?:ing)? |how .{1,50} collect(?:s|ed)? (?:rain ?)?water\b)/;
  const broadGuides = new Set(['opening-airway', 'first-aid-assessment', 'breathing-difficulty',
    'altered-mental-status', 'trauma', 'patient-warmth', 'head-to-toe', 'disaster-shelter', 'disaster-recovery']);
  function semanticGuides(documents, vector, domain, categoryIds, phrase = '') {
    const water = treatmentRequest(phrase);
    const matches = (root.OWLShardRank?.emergencyMatches?.(vector, domain) || [])
      .filter(({topic}) => !water || topic === 'drinking-water' || topic === 'sanitation');
    const first = matches[0];
    if (!first) return {domain, guides: [], nearby: []};
    if (!domain && first.score >= recognitionFloor) domain = first.field;
    if (!domain) return {domain, guides: [], nearby: []};

    const certain = first.score >= recognitionFloor && !broadGuides.has(first.topic) &&
      (first.score >= 0.55 || first.score - (matches[1]?.score ?? 0) >= 0.08);
    const nearby = [];
    const seen = new Set();
    for (const {topic, field, score} of matches) {
      if (score < Math.max(nearbyFloor, first.score - 0.13)) break;
      if (field !== domain) continue;
      const guides = guidesAt(documents, categoryIds, topic, locationsByTopic.get(topic));
      const lead = guides.find(guide => !seen.has(guide.id));
      if (!lead) continue;
      const companion = isArchive(lead) && guides.find(guide => guide.kind === 'section');
      const candidates = companion ? [lead, companion] : [lead];
      if (nearby.length + candidates.length > 3) continue;
      for (const candidate of candidates) {
        nearby.push({candidate, score});
        seen.add(candidate.id);
      }
      if (nearby.length === 3) break;
    }
    // A match only earns the reviewed label if the best guide is installed.
    if (certain && nearby[0]?.candidate.topic === first.topic) {
      return {domain, guides: nearby.filter(({score}) => score >= recognitionFloor)
        .map(({candidate}) => candidate), nearby: []};
    }
    return {domain, guides: [], nearby: nearby.map(({candidate}) => candidate)};
  }

  const routeName = text => text.replace(/^(?:first aid for|how to treat|what to do (?:for|about)|help with) /, '');
  const immediateRoutes = new Set(['carbon-monoxide', 'electrical-fire', 'gas-leak', 'house-fire',
    'drowning', 'anaphylaxis', 'choking', 'chemical-eye', 'food-outage']);
  function matchReviewedGuides(documents, phrase, categoryIds) {
    const name = routeName(phrase);
    const matches = sectionRoutes.map(route => {
      const score = route.name === name ? 3 :
        route.aliases.some(group => group.every(part => part.test(phrase))) ? 2 :
          route.headings.includes(name) ? 1 : 0;
      return {route, score};
    }).filter(match => match.score).sort((a, b) => b.score - a.score);
    const guidesForSection = ({topic, title, locations}) => {
      const ordered = [...locations].sort((a, b) =>
        Number(routePhrase(b[2]) === name) - Number(routePhrase(a[2]) === name));
      const guides = guidesAt(documents, categoryIds, topic, ordered);
      return guides.map((guide, index) => index ? guide : {...guide, title});
    };
    // Keep the tested response order for existing high-risk matches.
    const established = reviewedRoutes.filter(([, , , , patterns]) => patterns.some(pattern =>
      Array.isArray(pattern) ? pattern.every(part => part.test(phrase)) : pattern.test(phrase)));
    for (const row of established.filter(([topic]) => immediateRoutes.has(topic))) {
      const guides = guidesAt(documents, categoryIds, row[0], locationsByTopic.get(row[0]));
      if (!guides.length) continue;
      const exposure = row[0] === 'drowning' && matches.find(({route}) =>
        route.topic === 'ice-breakthrough' || route.topic === 'cold-water-injury');
      const [first, ...other] = exposure ? guidesForSection(exposure.route).filter(candidate =>
        !guides.some(guide => guide.href === candidate.href && guide.location === candidate.location)) : [];
      return first ? [guides[0], first, ...guides.slice(1), ...other] : guides;
    }
    for (const {route} of matches) {
      const guides = guidesForSection(route);
      if (guides.length) return guides;
    }
    for (const row of established) {
      const guides = guidesAt(documents, categoryIds, row[0], locationsByTopic.get(row[0]));
      if (guides.length) return guides;
    }
    return [];
  }

  function reviewedGuides(documents, {clauses, phrase}, categoryIds) {
    if (treatmentRequest(phrase)) {
      return guidesAt(documents, categoryIds, 'drinking-water', locationsByTopic.get('drinking-water'));
    }
    const whole = matchReviewedGuides(documents, phrase, categoryIds);
    const matched = new Map();
    // The latest clause leads when two independent events have reviewed matches.
    const ordered = [...clauses].reverse().sort((a, b) => Number(recentEvent.test(b)) - Number(recentEvent.test(a)));
    for (const clause of ordered) {
      for (const guide of matchReviewedGuides(documents, clause, categoryIds)) {
        if (!matched.has(guide.topic)) matched.set(guide.topic, []);
        const group = matched.get(guide.topic);
        if (!group.some(item => item.href === guide.href && item.location === guide.location)) group.push(guide);
      }
    }
    const groups = [...matched.values()];
    if (groups.length > 1) {
      return [...groups.map(group => group[0]), ...groups.flatMap(group => group.slice(1))];
    }
    return whole.length ? whole : groups.flat();
  }

  function reviewedGuide(documents, text, categoryIds) {
    return reviewedGuides(documents, currentEvents(text), categoryIds)[0];
  }

  const person = /\b(?:my (?:dad|father|mom|mum|mother|sister|brother|friend|son|daughter|partner|husband|wife|grandpa|grandma|uncle|aunt|child|kid|baby)|toddler|newborn|infant|child|baby|old (?:man|woman)|some(?:one|body)|person|he|she|i)\b/;
  const body = /\b(?:head|face|eyes?|ears?|nose|nostrils?|lips?|tongue|cheeks?|teeth|tooth|throat|jaw|neck|chest|ribs?|spine|back|belly|abdomen|stomach|skin|shoulders?|arms?|elbows?|wrists?|hands?|fingers?|hips?|legs?|knees?|ankles?|heels?|feet|foot|toes?)\b/;
  const symptom = /\b(?:hurts?|pain|stiff|tender|sore|numb\w*|tingl\w*|bruis\w*|swoll\w*|swell\w*|sick|not moving|wont move|cant (?:stand|walk|move)|dizz\w*|limp|pale|clammy|seeing spots)\b/;
  const injury = /\b(?:injur\w*|wounds?|broken|fractur\w*|fell|fallen|crash\w*|struck|got hit|hit (?:his|her|their|my)|cut|cutting|pinched|crush\w*|squash\w*|electrocut\w*|stuck|trapped|bitten|stung|bleed\w*|blood|burn\w*|attack\w*|tore open|torn open|ripped open)\b/;
  const medical = /\b(?:first aid|medical emergency|need an ambulance|no pulse|cardiac arrest|heart attack|breathing (?:fast|hard|slowly)|breath\w*|gasp\w*|wheez\w*|blue (?:lips?|face)|bluish|unconscious|not waking|not responding|wont wake|wont respond|hasnt moved|limp and still|collaps\w*|chok\w*|seizure\w*|convuls\w*|low blood sugar|epilep\w*|asthma|poison\w*|overdos\w*|bleeding|vomit\w*|puk(?:e[ds]?|ing)|throwing up|fever\w*|diarrh\w*|dehydrat\w*|rash\w*|infection|allergic reaction|anaphyla\w*|pregnan\w*|childbirth|afterbirth|snakebite\w*)\b/;
  const safety = /\b(?:emergency shelter|outside overnight|flood\w*|wildfire\w*|brush fire\w*|tornado\w*|hurricane\w*|tsunami\w*|earthquake\w*|landslide\w*|evacuat\w*|fire alarm|smoke (?:filling|in the house)|carbon monoxide|gas leak|power outage|blackout|lightning strike\w*|thunderstorm\w*|dirty (?:tap|drinking) water)\b/;
  const airway = /\b(?:breath\w*|gasp\w*|chok\w*|wheez\w*|(?:blue|bluish|grey|gray) (?:lips?|face)|airway|turn\w* (?:blue|purple))\b/;
  const awareness = /\b(?:wake|waking|conscious\w*|respond\w*|collaps\w*|faint\w*|passed out|lying still|lying there|not moving|no pulse)\b/;
  const hazard = /\b(?:danger\w*|hazards?|unsafe|warning|immediately|urgent|emergency|right now|severe|badly|cant stop)\b/;
  const severeInjury = /\b(?:stabbed|knifed|impaled|fell (?:off|from) (?:\w+ ){0,2}(?:roof|ladder|balcony|scaffold|cliff)|mauled|crushed under|suddenly (?:cant see|lost (?:his |her |my )?vision))\b/;
  const electricalHazard = /\b(?:outlets?|sockets?|sparks?|sparking|electricity|electrical|live wires?)\b/;
  const hazardObject = /\b(?:fumes?|fire|smoke|ice|gasoline|chemicals?|contaminat\w*)\b/;
  const visionLoss = phrase => /\b(?:eye|vision|sight)\b/.test(phrase) && /\b(?:flashes|floaters|dark curtain|gray curtain|grey curtain)\b/.test(phrase);
  const lodgedObject = phrase => /\b(?:nostrils?|nose|ears?)\b/.test(phrase) &&
    /\b(?:stuck|lodged|stuffed|jammed|pushed|insert\w*|object|bead|bug|pea|marble|lego|small toy)\b/.test(phrase);

  function emergencyDomain(phrase) {
    if (/\b(?:flood fill|carburetor choke|choke valve)\b/.test(phrase)) return '';
    if (treatmentRequest(phrase)) return 'safety';
    if (safety.test(phrase)) return 'safety';
    if (medical.test(phrase) || airway.test(phrase) || severeInjury.test(phrase) || visionLoss(phrase) ||
        lodgedObject(phrase) || /\b(?:jellyfish|envenom\w*)\b/.test(phrase) ||
        (body.test(phrase) && (symptom.test(phrase) || injury.test(phrase))) ||
        (person.test(phrase) && (symptom.test(phrase) || awareness.test(phrase) ||
          injury.test(phrase) && hazard.test(phrase)))) return 'health';
    return '';
  }

  function emergencyHint(phrase) {
    if (emergencyReference.test(phrase)) return '';
    if (electricalHazard.test(phrase) || hazardObject.test(phrase) || hazard.test(phrase)) return 'safety';
    if (body.test(phrase) || symptom.test(phrase) || injury.test(phrase) ||
        /\b(?:palms?|thumbs?|groin|limbs?|thighs?|calf|calves)\b/.test(phrase)) return 'health';
    return '';
  }

  function emergencySource(source, domain) {
    return (domain === 'health' ? /^(?:medical|first[_-]aid|health|dental)$/ :
      /^(?:shelter|preparedness|navigation|water.*|first[_-]aid|safety)$/).test(source.category);
  }

  function closestUrgent(documents, phrase, domain, ids) {
    let topics;
    if (treatmentRequest(phrase)) topics = ['drinking-water'];
    else if (domain === 'safety') topics = electricalHazard.test(phrase)
      ? ['electric-injury', 'downed-power-line'] : ['disaster-shelter'];
    else if (awareness.test(phrase) || /\b(?:cant|cannot|couldnt) (?:tell|see) if\b/.test(phrase) && airway.test(phrase))
      topics = ['unresponsive', 'first-aid-assessment'];
    else if (airway.test(phrase)) topics = ['breathing-difficulty', 'opening-airway'];
    else if (/\b(?:blood|bleed\w*|ha?emorrhag\w*)\b/.test(phrase)) topics = ['bleeding'];
    else topics = ['first-aid-assessment', 'trauma'];
    for (const filter of ids ? [ids, undefined] : [undefined]) {
      for (const topic of topics) {
        const guide = guidesAt(documents, filter, topic, locationsByTopic.get(topic)).find(item => !isArchive(item));
        if (guide) return guide;
      }
    }
    const guide = [...documents.values()].find(record => !isArchive(record) && emergencySource(record, domain)) ||
      [...documents.values()].find(record => !isArchive(record) && emergencySource(record, domain === 'health' ? 'safety' : 'health'));
    return guide;
  }

  function findUrgent(tasks, text) {
    const phrase = ' ' + (normalize(text).match(/[\p{L}\p{N}]+/gu) || []).join(' ') + ' ';
    return tasks.filter(task => task.href).map(task => {
      const score = Math.max(0, ...[task.task, ...task.keywords].map(value => {
        const words = tokens(value).join(' ');
        return (words.includes(' ') ? phrase.includes(' ' + words + ' ') : phrase.trim() === words)
          ? words.length : 0;
      }));
      return {task, score};
    }).filter(row => row.score).sort((a, b) => b.score - a.score)[0]?.task;
  }
  function heading(record) {
    const source = record.source_title || '';
    let title = record.title;
    if (record.location && title.endsWith(' · ' + record.location)) {
      title = title.slice(0, -record.location.length - 3);
    }
    if (source && title.startsWith(source + ' · ')) title = title.slice(source.length + 3);
    return !title || title === 'Section' ? source : title;
  }
  function orderedMatches(indexed, metadata, priority, words, terms, urgent, pediatricHealth) {
    const seen = new Set(), indexedFiles = new Set(indexed.map(({record}) => record.asset_id));
    const matches = [...indexed, ...metadata.filter(({record}) =>
      record.kind !== 'document' || !indexedFiles.has(record.asset_id))].filter(({record}) => {
      const key = record.href + '\0' + record.location;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    const score = hit => {
      const {record} = hit;
      const boost = isArchive(record) ? 0 : (Object.hasOwn(priority, record.asset_id) ? priority[record.asset_id] * 8 : 0);
      const title = heading(record) + ' ' + (record.source_title || '');
      const titleTerms = new Set(terms(title));
      const titleMatches = words.filter(word => titleTerms.has(word)).length;
      const titleScore = titleMatches && titleMatches === words.length ? 32 : 0;
      if (hit.indexed) {
        const guide = record.asset_id === urgent?.id ? 28 : 0;
        const childIllness = pediatricHealth && /\b(?:health and sicknesses of children|fever|childhood illnesses)\b/i.test(title) ? 18 : 0;
        return hit.score + boost + titleScore + guide + childIllness;
      }
      const lexical = hit.score % 10000 / 110;
      const exact = hit.score >= 100000;
      return (exact ? 150 : 20 + lexical * 12) + boost + titleScore;
    };
    return matches.map(hit => ({...hit, displayScore: score(hit)}))
      .sort((a, b) => (b.titleMatch || 0) - (a.titleMatch || 0) || b.displayScore - a.displayScore);
  }

  function strongMatch(hit, words, terms, intents) {
    if (!words.length) return false;
    if (hit.titleMatch) return true;
    if (!hit.indexed && hit.score >= 100000) return true;
    if (hit.indexed && hit.fullMatch && words.length >= 2 && hit.score >= 65) return true;
    if (hit.focused && hit.trusted && hit.score >= 115) return true;
    const {record} = hit;
    const title = new Set(terms(heading(record)));
    if (hit.indexed && intents.some(pattern => pattern.test(tokens(heading(record)).join(' ')))) return true;
    const evidence = new Set([...title, ...terms([record.source_title, record.description].join(' '))]);
    const covered = words.filter(word => evidence.has(word)).length;
    return covered >= Math.ceil(words.length * 0.75) && words.some(word => title.has(word)) &&
      (hit.indexed ? hit.score >= 65 : hit.displayScore >= 48);
  }

  async function loadRank(categoryIds) {
    let selection, table, paths = {};
    root.OWLShardSelection = value => { selection = value; };
    root.OWLShardModel = value => { table = value; };
    root.OWLSearchPaths = value => { paths = value; };
    try {
      if (generation) await script(local('search-paths.js'));
      const sharedScript = path => {
        if (!generation) return script(path);
        if (/^SEARCH\/(?:chunks|sources)\/[a-f0-9]{64}(?:\/\d{5})?\.js$/.test(path)) return script(path);
        const pinned = paths[path];
        if (!/^SEARCH\/shared\/[a-f0-9]{64}\.js$/.test(pinned)) return Promise.reject(Error('Missing pinned search file.'));
        return script(pinned);
      };
      await Promise.all([script(local('rank.js')), script(local('shards.js')), sharedScript('SEARCH/model.js')]);
      const loadReranker = () => script(local('rerank.js')).then(() => root.OWLReranker.create(sharedScript));
      const mobile = navigator.userAgentData?.mobile ?? /Android|iPhone|iPad/i.test(navigator.userAgent);
      return root.OWLShardRank.readerSearch(sharedScript, selection, table,
        {categoryIds, emergencySource, mobile, loadReranker});
    } catch (_) {
      return {warning: 'Full-text search is unavailable. Search still covers titles and topics.'};
    } finally {
      delete root.OWLShardSelection;
      delete root.OWLShardModel;
      delete root.OWLSearchPaths;
    }
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function passage(text, words) {
    const node = element('p', '', 'text');
    const pattern = words.length ? new RegExp('(' + words.map(word =>
      word.replace(/[.*+?^$${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'giu') : null;
    for (const [index, part] of (pattern ? text.split(pattern) : [text]).entries()) {
      node.append(index % 2 ? element('mark', part) : document.createTextNode(part));
    }
    return node;
  }

  function displayGuides(groups, hasAccess) {
    if (hasAccess) return groups;
    const result = [...groups];
    for (let index = 0; index < result.length; index++) {
      const record = result[index][0].record;
      if (!isArchive(record)) continue;
      const companion = result.findIndex(([{record: other}], at) =>
        at > index && other.topic === record.topic && !isArchive(other));
      if (companion >= 0) [result[index], result[companion]] = [result[companion], result[index]];
    }
    return result;
  }

  function mount(view, {open, openUrgent, archiveHref, urgentHref, archiveAccess, archiveLabel, tasks = [], priority = {}, categoryIds}) {
    const form = view.querySelector('form'), status = view.querySelector('#search-status');
    const list = view.querySelector('#search-results'), query = form.querySelector('#query');
    const category = form.querySelector('#search-category'), examples = form.querySelector('#search-examples');
    const correction = element('p', '', 'note search-correction');
    correction.hidden = true;
    status.after(correction);
    let timer, epoch = 0, prepared, documents, rankReady, lastRender, lastAccess;
    function message(text) {
      status.textContent = text;
      status.hidden = !text;
    }
    async function load() {
      message('Getting search ready…');
      let manifest, payload;
      root.OWLDiscoveryManifest = value => { manifest = value; };
      try {
        await script(local('manifest.js'));
        if (manifest?.format !== FORMAT || !/^SEARCH\/data\/[a-f0-9]{64}\.js$/.test(manifest.path)) {
          throw Error('The search information could not be read.');
        }
        root.OWLDiscoveryData = value => { payload = value; };
        await script(manifest.path);
        if (payload?.format !== FORMAT || payload.generation !== manifest.generation ||
            !Array.isArray(payload.records) || payload.records.length !== manifest.records) {
          throw Error('The search information does not match this drive.');
        }
        prepared = prepare(payload.records);
        documents = new Map(payload.records.filter(record => record.kind === 'document' && !record.legacy)
          .map(record => [record.id, record]));
        if (manifest.shards) rankReady = loadRank(categoryIds);
        message('');
      } catch (error) {
        message(error.message + ' Browse the books and guides from Home.');
      } finally {
        delete root.OWLDiscoveryManifest;
        delete root.OWLDiscoveryData;
      }
    }
    const ready = load();

    function resultLink(record, name, text, className) {
      const anchor = element('a', text, className);
      const topic = record.kind === 'topic';
      const archive = isArchive(record);
      anchor.href = topic ? '#/topic/' + encodeURIComponent(record.id.slice('topic:'.length))
        : archive ? archiveHref(record, name) : 'LIBRARY/' + record.href;
      anchor.addEventListener('click', event => {
        if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
          open(record, name, event);
        }
      });
      return anchor;
    }
    // One card per document, with its best match and a few distinct locations.
    function render(matches, scope, words = [], urgent, reviewed = [], nearby = []) {
      lastRender = [matches, scope, words, urgent, reviewed, nearby];
      lastAccess = archiveAccess?.();
      const preferred = new Map(), groups = [new Map(), new Map()], subjects = [];
      const preferredFiles = new Set(matches.filter(hit => hit.titleMatch)
        .map(({record}) => record.destination || record.href.split('#')[0]));
      for (const match of matches) {
        if (match.record.kind === 'topic') {
          subjects.push(match.record);
          continue;
        }
        const key = match.record.destination || match.record.href.split('#')[0];
        const bucket = preferredFiles.has(key) ? preferred : groups[Number(isArchive(match.record))];
        if (!bucket.has(key)) bucket.set(key, []);
        bucket.get(key).push(match);
      }
      const items = document.createDocumentFragment();
      if (urgent) {
        const browse = urgent.href === '#/';
        const card = element('article', '', browse ? 'result' : 'result urgent-result');
        if (browse) card.dataset.nearby = 'urgent-guides';
        else card.append(element('span', 'Urgent', 'label urgent'));
        card.append(element('h3', urgent.task));
        const archive = urgent.format === 'zim';
        const byline = archive && archiveLabel?.(urgent.id);
        if (byline) card.append(element('small', byline));
        const link = element('a', browse ? 'Browse Home' : 'Open', 'button');
        link.href = archive ? urgentHref(urgent) : urgent.href;
        link.addEventListener('click', event => {
          if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            if (!browse) openUrgent(urgent, event);
          }
        });
        card.append(link);
        items.append(card);
      }
      function resultCard([{record, indexed = false}, ...others], reviewRank) {
        const isReviewed = reviewRank !== undefined;
        const card = element('article', '', isReviewed ? 'result urgent-result' : 'result');
        card.dataset.indexed = String(indexed);
        if (isReviewed) {
          card.dataset.reviewed = record.topic;
          card.dataset.reviewRank = String(reviewRank);
          card.append(element('span', 'Urgent', 'label urgent'));
        }
        const archive = isArchive(record), name = heading(record);
        const source = record.source_title !== name ? record.source_title : '';
        const where = archive ? archiveLabel?.(record.asset_id || record.id) : record.location;
        const byline = [source, where].filter(Boolean).join(' · ');
        if (byline) card.append(element('small', byline));
        card.append(element('h3', name));
        if (record.description) {
          card.append(passage(/[.!?…:]$/.test(record.description) ? record.description : record.description + '…', words));
          if (indexed) {
            const license = normalize(record.license).replace(/[-\s]+/g, ' ');
            const alreadyCredited = license && normalize(record.attribution).replace(/[-\s]+/g, ' ').includes(license);
            const credit = [record.attribution, alreadyCredited ? '' : record.license].filter(Boolean).join(' · ');
            if (credit) card.append(element('small', credit, 'attribution'));
          }
        }
        const locations = new Set([record.href + '\0' + record.location]);
        const places = others.filter(({record: other}) => {
          if (other.kind !== 'section' && other.kind !== 'article' && !other.href.includes('#')) return false;
          const key = other.href + '\0' + other.location;
          if (locations.has(key)) return false;
          locations.add(key);
          return true;
        }).slice(0, 3);
        if (places.length) {
          card.append(element('p', 'Also in this document', 'also-label'));
          const more = element('ul', '', 'also');
          more.setAttribute('aria-label', 'Also in this document');
          for (const {record: other} of places) {
            const item = element('li', '');
            const title = heading(other);
            item.append(resultLink(other, title, title === name && other.location ? isArchive(other) ? other.archiveSection || title : other.location : title));
            more.append(item);
          }
          card.append(more);
        }
        card.append(resultLink(record, name, 'Open', 'button'));
        return card;
      }
      const guides = new Map(), firstForTopic = new Map(), archiveTopics = new Set();
      const fileFor = record => record.destination || record.href.split('#')[0];
      for (const record of reviewed) {
        if (!firstForTopic.has(record.topic)) firstForTopic.set(record.topic, fileFor(record));
        if (isArchive(record)) archiveTopics.add(record.topic);
      }
      const leadFiles = new Set(firstForTopic.values());
      for (const record of reviewed) {
        const file = fileFor(record);
        if (file !== firstForTopic.get(record.topic) && leadFiles.has(file) && !archiveTopics.has(record.topic)) continue;
        const key = record.topic + '\0' + file;
        if (!guides.has(key)) guides.set(key, []);
        guides.get(key).push({record});
      }
      const ranked = [...guides.values()];
      for (const group of displayGuides(ranked, lastAccess)) items.append(resultCard(group, ranked.indexOf(group)));
      for (const record of nearby) {
        const card = resultCard([{record}]);
        card.dataset.nearby = record.topic || record.id;
        items.append(card);
      }
      for (const hits of preferred.values()) items.append(resultCard(hits));
      for (const group of groups) {
        if (!group.size) continue;
        const section = element('section', '', 'result-group');
        if (group === groups[1]) {
          section.append(element('h2', 'In encyclopedias', 'label encyclopedia-results'));
        }
        for (const hits of group.values()) section.append(resultCard(hits));
        items.append(section);
      }
      if (subjects.length) {
        const panel = element('section', '', 'panel');
        panel.append(element('h3', 'Subjects'));
        const links = element('div', '', 'chips plain');
        for (const subject of subjects) links.append(resultLink(subject, subject.title, subject.title));
        panel.append(links);
        items.append(panel);
      }
      list.replaceChildren(items);
      list.dataset.searchScope = scope;
      return preferred.size + groups[0].size + groups[1].size + subjects.length + guides.size + nearby.length + Number(Boolean(urgent));
    }
    const passageNote = 'No reviewed guide matched. These passages may help.';
    const noMatch = 'No close match. Browse Urgent guides and categories on Home.';
    const urgentShelf = {task: 'Urgent guides', href: '#/'};
    function appendBrowseHome() {
      const home = element('a', 'Browse Home', 'button');
      home.href = '#/';
      list.append(home);
    }
    async function routeByMeaning(text, phrase, domain, ids) {
      const engine = !phrase.includes(' ') || emergencyReference.test(phrase) ? undefined : await rankReady;
      const vector = await engine?.embed?.(text);
      return semanticGuides(documents, vector, domain, ids, phrase);
    }

    async function showSemanticEmergency(text, phrase, words, ids, cancelled, correctionText) {
      const semantic = await routeByMeaning(text, phrase, '', ids);
      if (cancelled() || !semantic.domain) return false;
      if (correctionText) showCorrection(correctionText);
      list.dataset.emergency = 'true';
      if (semantic.guides.length) showGuides(semantic.guides);
      else await runEmergency(text, phrase, words, ids, semantic.domain, cancelled, semantic);
      return true;
    }

    async function runEmergency(text, phrase, words, ids, domain, cancelled, routing) {
      const nearby = closestUrgent(documents, phrase, domain, ids);
      const initial = nearby ? [nearby] : [];
      render([], 'indexed', [], nearby ? undefined : urgentShelf, [], initial);
      message(rankReady ? 'Searching… ' + passageNote : passageNote);
      const semantic = await routing;
      if (cancelled()) return;
      if (semantic.guides.length) {
        showGuides(semantic.guides);
        return;
      }
      const engine = words.length <= 32 && await rankReady;
      if (cancelled()) return;
      const indexed = await engine?.emergency?.(text, {
        ids, domain, nearby: semantic.nearby, allowExact: !initial.length, cancelled,
        select(hits, intent) {
          const {terms, nearbyPassages} = root.OWLShardRank;
          const matches = orderedMatches(hits, [], priority, intent.query, terms, undefined, intent.pediatricHealth);
          const strong = new Set(matches.filter(hit => strongMatch(hit, intent.query, terms, intent.titlePatterns)));
          return nearbyPassages(matches, strong, intent.query, heading);
        },
      }) || [];
      if (cancelled()) return;
      const found = indexed.length || semantic.nearby.length;
      render(indexed, 'complete', words, found ? undefined : urgentShelf, [],
        found ? semantic.nearby : initial);
      if (found) appendBrowseHome();
      message(found || initial.length ? passageNote : noMatch);
    }

    function showGuides(guides) {
      const count = render([], 'complete', [], undefined, guides);
      message(count === 1 ? '1 result.' : count + ' results, best first.');
    }
    async function run(event) {
      event?.preventDefault();
      clearTimeout(timer);
      const mine = ++epoch;
      const cancelled = () => mine !== epoch;
      const text = query.value.trim(), selected = category.value;
      examples.hidden = Boolean(text);
      correction.hidden = true;
      if (!text) {
        delete list.dataset.emergency;
        render([], 'catalog');
        if (prepared) message('');
        return;
      }
      await ready;
      if (cancelled() || !prepared) return;
      try {
        const ids = selected && await categoryIds(selected);
        if (cancelled()) return;
        await searchText(text, selected, ids, cancelled);
      } catch (error) {
        if (cancelled()) return;
        render([], 'catalog');
        message(error.message);
      }
    }

    async function searchText(text, selected, ids, cancelled, isCorrection = false) {
      const words = tokens(text);
      const events = currentEvents(text);
      const {phrase} = events;
      const guides = reviewedGuides(documents, events, ids);
      const domain = emergencyDomain(phrase);
      list.dataset.emergency = String(Boolean(guides.length || domain));
      if (guides.length) {
        if (isCorrection) showCorrection(text);
        showGuides(guides);
        return true;
      }
      const activeText = events.excluded ? phrase : text;
      const hint = emergencyHint(phrase);
      if (domain) {
        if (isCorrection) showCorrection(text);
        await runEmergency(activeText, phrase, words, ids, domain, cancelled, routeByMeaning(activeText, phrase, domain, ids));
        return true;
      }
      const engine = await rankReady;
      if (cancelled()) return;
      const locations = engine?.navigationLocations?.(phrase) || [];
      const navigation = locations.flatMap(([id, page, title]) => {
        const record = guideAt(documents, ids, undefined, title, id, page);
        return record ? [{record, indexed: true}] : [];
      });
      if (navigation.length) {
        const count = render(navigation, 'complete', words);
        message(count === 1 ? '1 result.' : count + ' results, best first.');
        return true;
      }
      if (hint) {
        if (rankReady) message('Searching…');
        if (await showSemanticEmergency(activeText, phrase, words, ids, cancelled, isCorrection && text)) return true;
        if (cancelled()) return;
      }
      if (words.length > 32) {
        if (!hint) throw Error('Use at most 32 different search words.');
        list.dataset.emergency = 'true';
        await runEmergency(activeText, phrase, words, ids, hint, cancelled, routeByMeaning(activeText, phrase, hint, ids));
        return true;
      }
      const scope = ids ? prepared.filter(({record}) => ids.has(record.asset_id) ||
        record.kind === 'topic' && record.source_ids.some(id => ids.has(id))) : prepared;
      const catalog = search(scope, text, 'all', 90);
      const urgent = findUrgent(ids ? tasks.filter(task => ids.has(task.id)) : tasks, activeText);
      let count, showingPassages = false, warning = '';
      const showHits = (hits, intent, progress) => {
        const ranker = root.OWLShardRank;
        const [queryTerms, terms] = intent ? [intent.query, ranker.terms] : [words, tokens];
        const matches = orderedMatches(hits, catalog, priority, queryTerms, terms, urgent, intent?.pediatricHealth);
        const strong = new Set(matches.filter(hit => strongMatch(hit, queryTerms, terms, intent?.titlePatterns || [])));
        const passages = hits.length && !urgent && (intent?.emergency || strong.size === 0)
          ? ranker.nearbyPassages(matches, strong, queryTerms, heading) : [];
        showingPassages = passages.length > 0;
        count = render(showingPassages ? passages : [...strong].slice(0, 70), intent ? 'indexed' : 'catalog', words, urgent);
        if (progress) {
          const status = progress === 'ranked' ? 'Still looking for better matches…' : 'Searching…';
          message(showingPassages ? status + ' ' + passageNote : status);
        }
        return count;
      };
      if (rankReady) message('Searching…');
      showHits([]);
      if (engine) {
        try {
          warning = engine.warning || '';
          if (await engine.query?.(text, {
            category: selected, ids, urgent, cancelled, spellingRetry: isCorrection, display: showHits,
            displayExact: hits => hits.length ? (count = render(hits, 'indexed', words)) : 0,
            applyCorrection: suggestion => searchText(suggestion, selected, ids, cancelled, true),
            tryEmergency: words.length > 1 && (() => showSemanticEmergency(activeText, phrase, words, ids, cancelled)),
          })) return true;
          if (cancelled()) return;
        } catch (error) {
          if (cancelled()) return;
          warning = error.message + ' Showing what was found.';
        }
      }
      if (hint && !list.querySelector('article.result')) {
        list.dataset.emergency = 'true';
        await runEmergency(activeText, phrase, words, ids, hint, cancelled, routeByMeaning(activeText, phrase, hint, ids));
        return true;
      }
      if (isCorrection) {
        if (!count) return false;
        showCorrection(text);
      }
      list.dataset.searchScope = 'complete';
      if (!count || showingPassages) appendBrowseHome();
      let summary = noMatch;
      if (showingPassages) summary = passageNote;
      else if (count) summary = count + ' result' + (count === 1 ? '.' : 's, best first.');
      message([warning, summary].filter(Boolean).join(' '));
      return Boolean(count);
    }
    function showCorrection(text) {
      correction.textContent = 'Showing results for “' + text + '”.';
      correction.hidden = false;
    }
    form.addEventListener('submit', run);
    query.addEventListener('input', () => {
      clearTimeout(timer);
      ++epoch;
      examples.hidden = Boolean(query.value.trim());
      if (!query.value.trim()) run();
      else timer = setTimeout(run, 350);
    });
    for (const example of form.querySelectorAll('[data-query]')) {
      example.addEventListener('click', () => { query.value = example.dataset.query; query.focus(); run(); });
    }
    category.addEventListener('change', run);
    return (force = false) => {
      if (lastRender && (force || lastRender[4].length && lastAccess !== archiveAccess?.())) render(...lastRender);
    };
  }

  const api = {normalize, tokens, prepare, search, safeHref, script, local, isArchive, mount,
    reviewedGuide, reviewedGuides: (documents, text, ids) => reviewedGuides(documents, currentEvents(text), ids),
    semanticGuides, displayGuides, emergencyDomain: text => emergencyDomain(currentEvents(text).phrase), emergencySource, closestUrgent};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OWLDiscovery = api;
  if (typeof document !== 'undefined' && document.querySelector('#reader-view')) {
    script(generation ? local('reader.js') : 'INDEX/reader.js').catch(() => {});
  }
})(globalThis);
