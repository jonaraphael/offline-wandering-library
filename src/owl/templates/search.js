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
  function mergeRanked(indexed, metadata, limit = 40) {
    const exact = metadata.filter(hit => hit.score >= 100000).slice(0, 2);
    const full = metadata.filter(hit => hit.score >= 10000 && hit.score < 100000).slice(0, 2);
    const seen = new Set();
    const first = indexed.slice(0, 3);
    const head = first[0]?.focused ? [...first, ...exact] : [...exact, ...first];
    return [...head, ...full, ...indexed.slice(3), ...metadata].filter(({record}) => {
      const key = record.href + '\0' + record.location;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
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
      [/\b(?:swallow\w*|drank|drink\w*|ate|eaten|unknown amount|open bottle|too many)\b/,
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
        /\b(?:bite|bites|bit|bitten|sank .{0,12}teeth|broke the skin|scratch\w*)\b/],
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
    ['food-outage', 'Food safety during a power outage', 'fema_are_you_ready_2020', 26, [
      /\b(?:food safety .{0,20}(?:power|outage)|power (?:outage|cut) .{0,20}(?:food|fridge|freezer))\b/,
      [/\b(?:power|electricity|blackout|outage)\b/, /\b(?:fridge|refrigerator|freezer|thaw\w*|meat|milk|perishable\w*)\b/],
    ]],
    ['sanitation', 'Emergency sanitation and toilets', 'hesperian_en_cgeh_2012_07', 2, [
      /\b(?:emergency sanitation|toilet (?:wont|doesnt|cant) flush|no working toilets?|bucket toilet|human waste after)\b/,
      [/\b(?:toilets?|bathroom|latrine|human waste|sewer)\b/, /\b(?:no plumbing|without water|no (?:running )?water|nowhere to go|emergency|disaster|no sewer|not flushing)\b/],
    ]],
  ];

  function reviewedGuide(documents, text, categoryIds) {
    const phrase = normalize(text).replace(/['’]/g, '').match(/[\p{L}\p{N}]+/gu)?.join(' ') || '';
    const route = reviewedRoutes.find(([, , , , patterns]) => patterns.some(pattern =>
      Array.isArray(pattern) ? pattern.every(part => part.test(phrase)) : pattern.test(phrase)));
    if (!route) return;
    const [topic, title, id, locator] = route;
    const guide = documents.get(id);
    if (!guide || categoryIds && !categoryIds.has(id)) return;
    if (typeof locator === 'number' && /\.pdf$/i.test(guide.href)) {
      return {...guide, topic, title, description: '', kind: 'section',
        href: guide.href + '#page=' + locator, location: 'Page ' + locator};
    }
    if (id === 'wikimed_en' && isArchive(guide)) {
      return {...guide, topic, title, description: '', kind: 'article',
        articleTitle: locator.replace(/_/g, ' '), location: 'Archive path: ' + locator};
    }
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
      .sort((a, b) => b.displayScore - a.displayScore);
  }

  function strongMatch(hit, words, terms, intents) {
    if (!words.length) return false;
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

  function nearbyPassages(matches, strong, words, terms) {
    const chosen = [];
    const documents = new Set();
    const minimum = Math.max(2, Math.ceil(words.length / 2));
    for (const hit of matches) {
      if (!hit.indexed) continue;
      const {record} = hit;
      const document = record.destination || record.href.split('#')[0];
      if (documents.has(document)) continue;
      if (!strong.has(hit)) {
        const matched = hit.matchedTerms ?? 0;
        if (hit.score < 55 || matched < minimum) continue;
        const visible = new Set(terms(heading(record) + ' ' + (record.description || '')));
        const visibleMatches = words.filter(word => visible.has(word)).length;
        // Some indexed sources cannot show excerpts. Require stronger posting
        // evidence when the heading and visible excerpt share fewer words.
        if (visibleMatches < 2 &&
            (record.description || hit.score < 80 || matched < Math.max(4, Math.ceil(words.length * 2 / 3)))) continue;
      }
      chosen.push(hit);
      documents.add(document);
      if (chosen.length === 3) break;
    }
    return chosen;
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
      const ranker = root.OWLShardRank;
      const indexed = ranker.classic(sharedScript, selection, table, async (index, encode, read, query, category, ...options) => {
        const ids = category && await categoryIds(category);
        const scoped = ids ? {...index, sources: index.sources.filter(source => ids.has(source.id))} : index;
        return ranker.search(scoped, encode, read, query, 'all', ...options);
      });
      const mobile = navigator.userAgentData?.mobile ?? /Android|iPhone|iPad/i.test(navigator.userAgent);
      if (!selection.reranker || mobile) return {rank: indexed};
      let reranker;
      async function rank(text, category, limit, cancelled, onProgress) {
        const all = await indexed(text, category, Math.max(limit, 50), cancelled,
          (hits, scope) => onProgress(hits.slice(0, limit), scope));
        const initial = all.slice(0, limit);
        if (cancelled() || initial.length < 2) return initial;
        onProgress(initial, 'ranked');
        try {
          reranker ??= script(local('rerank.js')).then(() => root.OWLReranker.create(sharedScript));
          const rerank = await reranker;
          const head = all.slice(0, 3);
          const shortlist = all.slice(3, 53);
          const rescored = await rerank(text, shortlist, cancelled);
          const remaining = [...rescored, ...all.slice(head.length + shortlist.length)];
          return cancelled() ? [] : [...head, ...ranker.topResults(remaining, limit - head.length)];
        } catch (_) {
          reranker = undefined;
          return initial;
        }
      }
      return {rank};
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

  function mount(view, {open, openUrgent, tasks = [], priority = {}, categoryIds}) {
    const form = view.querySelector('form'), status = view.querySelector('#search-status');
    const list = view.querySelector('#search-results'), query = form.querySelector('#query');
    const category = form.querySelector('#search-category'), examples = form.querySelector('#search-examples');
    let timer, epoch = 0, prepared, documents, rankReady;
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
        : archive ? '#open-encyclopedia' : 'LIBRARY/' + record.href;
      if (archive) anchor.setAttribute('aria-haspopup', 'dialog');
      anchor.addEventListener('click', event => {
        if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
          open(record, name, event);
        }
      });
      return anchor;
    }
    // One card per document, with its best match and a few distinct locations.
    function render(matches, scope, words = [], urgent, reviewed) {
      const groups = [new Map(), new Map()], subjects = [];
      for (const match of matches) {
        if (match.record.kind === 'topic') {
          subjects.push(match.record);
          continue;
        }
        const bucket = groups[Number(isArchive(match.record))];
        const key = match.record.destination || match.record.href.split('#')[0];
        if (!bucket.has(key)) bucket.set(key, []);
        bucket.get(key).push(match);
      }
      const items = document.createDocumentFragment();
      if (urgent) {
        const card = element('article', '', 'result urgent-result');
        card.append(element('span', 'Urgent', 'label urgent'), element('h3', urgent.task));
        const archive = urgent.format === 'zim';
        const link = element('a', archive ? 'How to open' : 'Open', 'button');
        link.href = archive ? '#open-encyclopedia' : urgent.href;
        if (archive) link.setAttribute('aria-haspopup', 'dialog');
        link.addEventListener('click', event => {
          if (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
            openUrgent(urgent, event);
          }
        });
        card.append(link);
        items.append(card);
      }
      function resultCard([{record, indexed = false}, ...others], isReviewed = false) {
        const card = element('article', '', isReviewed ? 'result urgent-result' : 'result');
        card.dataset.indexed = String(indexed);
        if (isReviewed) {
          card.dataset.reviewed = record.topic;
          card.append(element('span', 'Urgent', 'label urgent'));
        }
        const archive = isArchive(record), name = heading(record);
        const source = record.source_title !== name ? record.source_title : '';
        const where = archive ? 'opens in Kiwix' : record.location;
        const byline = [source, where].filter(Boolean).join(' · ');
        if (byline) card.append(element('small', byline));
        card.append(element('h3', name));
        if (record.description) card.append(passage(/[.!?…:]$/.test(record.description)
          ? record.description : record.description + '…', words));
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
            item.append(resultLink(other, title, title === name && other.location ? other.location : title));
            more.append(item);
          }
          card.append(more);
        }
        if (archive && record.kind !== 'document') {
          card.append(element('p', 'In Kiwix, look up “' + (record.articleTitle || name) + '”.', 'note'));
        }
        card.append(resultLink(record, name, archive ? 'How to open' : 'Open', 'button'));
        return card;
      }
      if (reviewed) items.append(resultCard([{record: reviewed}], true));
      for (const group of groups) {
        if (!group.size) continue;
        const section = element('section', '', 'result-group');
        if (group === groups[1]) {
          section.append(element('h2', 'In encyclopedias (open in Kiwix)', 'label encyclopedia-results'));
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
      return groups[0].size + groups[1].size + subjects.length + Number(Boolean(urgent || reviewed));
    }
    async function run(event) {
      event?.preventDefault();
      clearTimeout(timer);
      const mine = ++epoch;
      const cancelled = () => mine !== epoch;
      const text = query.value.trim(), selected = category.value;
      examples.hidden = Boolean(text);
      if (!text) {
        render([], 'catalog');
        if (prepared) message('');
        return;
      }
      await ready;
      if (cancelled() || !prepared) return;
      try {
        const ids = selected && await categoryIds(selected);
        if (cancelled()) return;
        const words = tokens(text);
        if (words.length > 32) throw Error('Use at most 32 different search words.');
        const guide = reviewedGuide(documents, text, ids);
        if (guide) {
          render([], 'complete', [], undefined, guide);
          message('1 result.');
          return;
        }
        const scope = ids ? prepared.filter(({record}) => ids.has(record.asset_id) ||
          record.kind === 'topic' && record.source_ids.some(id => ids.has(id))) : prepared;
        let terms = tokens, queryTerms = words, intent;
        const catalog = search(scope, text, 'all', 90);
        const urgent = findUrgent(ids ? tasks.filter(task => ids.has(task.id)) : tasks, text);
        const passageNote = 'No reviewed guide matched. These passages may help.';
        let count, showingPassages = false, warning = '';
        const showHits = (hits, phase) => {
          const matches = orderedMatches(hits, catalog, priority, queryTerms, terms, urgent, intent?.pediatricHealth);
          const strong = new Set(matches.filter(hit => strongMatch(hit, queryTerms, terms, intent?.titlePatterns || [])));
          const passages = !urgent && (intent?.emergency || strong.size === 0)
            ? nearbyPassages(matches, strong, queryTerms, terms) : [];
          showingPassages = passages.length > 0;
          count = render(showingPassages ? passages : [...strong].slice(0, 70), phase, words, urgent);
        };
        if (rankReady) message('Searching…');
        showHits([], 'catalog');
        if (rankReady) {
          try {
            const engine = await rankReady;
            if (cancelled()) return;
            warning = engine.warning || '';
            if (engine.rank) {
              const ranker = root.OWLShardRank;
              terms = ranker.terms;
              intent = ranker.prepareQuery(text, () => null);
              queryTerms = intent.query;
              let rankedText = text;
              if (!intent.emergency && urgent?.keywords.includes('wound')) rankedText += ' wound care';
              if (!intent.emergency && urgent?.keywords.includes('scald')) rankedText += ' burn treatment';
              if (!intent.deliveryQuery && !intent.postpartum && urgent?.keywords.includes('childbirth')) rankedText += ' childbirth';
              const hits = await engine.rank(rankedText, selected, 85, cancelled, (hits, phase) => {
                if (cancelled()) return;
                showHits(hits, 'indexed');
                const progress = phase === 'refining' || phase === 'ranked' ? 'Still looking for better matches…' : 'Searching…';
                message(showingPassages ? progress + ' ' + passageNote : progress);
              });
              if (cancelled()) return;
              showHits(hits, 'complete');
            }
          } catch (error) {
            if (cancelled()) return;
            warning = error.message + ' Showing what was found.';
          }
        }
        list.dataset.searchScope = 'complete';
        if (!count || showingPassages) {
          const home = element('a', 'Browse Home', 'button');
          home.href = '#/';
          list.append(home);
        }
        let summary = 'No close match. Browse Urgent guides and categories on Home.';
        if (showingPassages) summary = passageNote;
        else if (count) summary = count + ' result' + (count === 1 ? '.' : 's, best first.');
        message([warning, summary].filter(Boolean).join(' '));
      } catch (error) {
        render([], 'catalog');
        message(error.message);
      }
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
  }

  const api = {normalize, tokens, prepare, search, mergeRanked, safeHref, script, local, isArchive, mount, reviewedGuide};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OWLDiscovery = api;
  if (typeof document !== 'undefined' && document.querySelector('#reader-view')) {
    script(generation ? local('reader.js') : 'INDEX/reader.js').catch(() => {});
  }
})(globalThis);
