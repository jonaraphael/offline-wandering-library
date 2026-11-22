/* Offline ranking over independently packed, selected source shards. */
(function (root) {
  'use strict';
  const stop = new Set('a an and are as at be by do does for from how i in is it of on or the to use what when where with you your'.split(' '));
  const fold = text => text.toLowerCase().normalize('NFKD').replace(/\p{M}/gu, '');
  const words = text => fold(text).match(/[\p{L}\p{N}]+/gu) || [];
  const normalize = text => words(text).join(' ');

  function stem(word) {
    if (word.length > 4 && word.endsWith('ies')) return word.slice(0, -3) + 'y';
    if (word.length > 5 && word.endsWith('oes')) return word.slice(0, -2);
    for (const suffix of ['ing', 'ed', 'es', 's']) {
      if (word.length > suffix.length + 3 && word.endsWith(suffix) && !/(ss|us)$/.test(word)) {
        word = word.slice(0, -suffix.length);
        if ((suffix === 'ing' || suffix === 'ed') && /(bb|dd|gg|mm|nn|pp|rr|tt)$/.test(word)) word = word.slice(0, -1);
        break;
      }
    }
    return word.length > 4 && word.endsWith('e') ? word.slice(0, -1) : word;
  }

  function terms(text) {
    return [...new Set(words(text).filter(word => word.length > 1 && word.length <= 50 && !stop.has(word)).map(stem))];
  }

  // Trigger phrases describe an intent. Each evidence phrase is an independent
  // way a record can cover it, including when its excerpt cannot be displayed.
  const rules = [
    ['health', /\b(?:bleeding|ha?emorrhag\w*|blood loss|los\w* .{0,26}blood|blood (?:spurting|gushing)|(?:stop|control) .{0,12}bleed\w*)\b/,
      'severe bleeding|heavy bleeding|stop bleeding|bleeding wounds|external hemorrhage|direct pressure|tourniquet|hemorrhage|bleeding'],
    ['health', /\b(?:wound (?:care|infection|closure)|(?:cut|wound)s? .{0,38}(?:stitches|sutures|gapes|gaping)|without (?:stitches|sutures)|clean\w* .{0,16}(?:wound|deep cut))\b/,
      'open wounds|cleaning wounds|wound care|wound closure|wound dressing|wound infection|laceration|wounds'],
    ['health', /^(?=.*\b(?:bleed\w*|ha?emorrhag\w*)\b).*\b(?:postpartum|after (?:\w+ ){0,3}(?:giv(?:e|es|ing) birth|childbirth|delivery))\b/,
      'postpartum hemorrhage|postpartum bleeding|bleeding after birth|uterine atony|third stage of labor'],
    ['health', /\b(?:childbirth|giv(?:e|es|ing) birth|(?:deliver|delivery|catch)\w* .{0,16}(?:baby|child)|baby is coming|birth at home|home birth|(?:labor|labour) and (?:birth|delivery)|contractions .{0,26}(?:labor|labour))\b/,
      'pushing stage|deliver the baby|catch the baby|help the baby|labor and birth|stages of labor|giving birth|childbirth|obstetric delivery'],
    ['health', /\b(?:cpr|cardiopulmonary resuscitation|chest compressions|cardiac arrest|(?:not|stopped|isnt|isn t) breathing|restart breathing)\b/,
      'cardiopulmonary resuscitation|chest compressions|basic life support|rescue breathing|cardiac arrest|cpr'],
    ['health', /\b(?:choking|choke[ds]?|airway obstruction|heimlich|food (?:is )?stuck|something stuck .{0,12}throat)\b/,
      'choking|airway obstruction|abdominal thrusts|heimlich|blocked airway'],
    ['health', /\b(?:anaphylax\w*|severe allergic reaction|throat .{0,12}swell\w*|epipen)\b/,
      'anaphylaxis|anaphylactic shock|severe allergic reaction|epinephrine|adrenaline autoinjector'],
    ['health', /\b(?:heat ?stroke|heat exhaustion|heat illness|hot and confused|overheat\w* .{0,22}confus\w*)\b/,
      'heat stroke|heatstroke|heat exhaustion|heat illness|hyperthermia'],
    ['health', /\b(?:hypothermia|stopped shivering|dangerously cold|cold exposure)\b/,
      'hypothermia|cold exposure|rewarming|body temperature'],
    ['health', /\b(?:frostbite|frozen skin|white and numb|numb and white|numb .{0,15}fingers .{0,16}snow)\b/,
      'frostbite|frostnip|cold injury|frozen skin'],
    ['health', /\b(?:scald\w*|burns? (?:first aid|treatment)|(?:boiling|scalding) water .{0,16}(?:skin|arm|hand|leg)|(?:treat|cool) .{0,12}(?:burns?|burned skin))\b/,
      'first aid for burns|scalds|burn wounds|thermal burns|burn treatment|burns'],
    ['health', /\b(?:broken (?:bone|arm|leg|ankle)|fracture|splint|looks crooked|immobiliz\w* .{0,16}(?:joint|limb))\b/,
      'broken bones|splinting fractures|fracture|dislocation|splint|immobilization'],
    ['health', /\b(?:snakebites?|snake (?:bite|bit)|bitten by a snake)\b/,
      'snakebite|snake bite|snake envenomation|venomous snake bites'],
    ['health', /\b(?:poisoning|drank .{0,24}(?:bleach|detergent|cleaning|cleaner)|swallow\w* .{0,16}(?:poison|bleach|cleaner))\b/,
      'accidental poisoning|poisoned|ingested poisons|poison control|poisoning'],
    ['health', /\b(?:seizures?|convulsions?|shaking all over)\b/,
      'seizure first aid|epileptic seizure|seizures|convulsions'],
    ['health', /\b(?:diarrh\w*|oral rehydration|watery stools|dehydration|(?:cannot|can t|unable to) keep (?:fluids?|liquids?|water|(?:a )?drink) down)\b/,
      'oral rehydration|dehydration|diarrhea|diarrhoea|acute vomiting|rehydration drink'],
    ['health', /\b(?:hypoglyc\w*|low blood sugar|diabet\w* .{0,38}(?:sweat\w*|confus\w*))\b/,
      'hypoglycemia|hypoglycaemia|low blood sugar|insulin shock'],
    ['health', /\b(?:stroke (?:signs|symptoms|first aid)|face .{0,8}droop\w*|slurred speech|(?:having|had|recognize) a stroke)\b/,
      'stroke|cerebrovascular accident|facial droop|transient ischemic attack'],
    ['health', /\b(?:asthma attack|(?:asthma|asthmatic) .{0,24}(?:wheez\w*|breath\w*)|rescue inhaler)\b/,
      'asthma attack|acute asthma|asthma exacerbation|bronchospasm|rescue inhaler'],
    ['health', /\b(?:knocked out tooth|tooth .{0,16}knocked out|dental avulsion|avulsed tooth)\b/,
      'avulsed tooth|dental avulsion|knocked out tooth|tooth injuries|dental trauma'],
    ['health', /\b(?:carbon monoxide|generator .{0,12}(?:inside|indoors|exhaust))\b/,
      'carbon monoxide poisoning|carbon monoxide|generator exhaust'],
    ['water', /\b(?:purif\w* water|water purification|(?:make|treat) .{0,18}water .{0,12}(?:safe|drink)|(?:only|untreated) water .{0,16}(?:creek|stream|river|pond)|emergency drinking water)\b/,
      'emergency drinking water|drinking water treatment|water purification|drinking water disinfection|boiling water|waterborne pathogens'],
    ['survival', /\b(?:fire ?starting|start\w* .{0,16}(?:camp)?fire|(?:start|light|make|build|get) .{0,14}(?:campfire|fire going)|light a fire|fire without .{0,18}(?:lighter|matches)|(?:wet|soaked) matches|fire ?craft)\b/,
      'fire starting|firecraft|fire making|building a fire|starting a fire|fire without matches|tinder|kindling'],
    ['survival', /\b(?:emergency shelter|survival shelter|outside overnight|overnight .{0,20}without .{0,6}tent|tornado .{0,24}(?:cover|shelter|close)|(?:cover|shelter) .{0,24}tornado)\b/,
      'emergency shelter|tornado shelter|storm shelter|survival shelter|improvised shelter|outdoor shelter|shelter in place'],
    ['', /\b(?:root cellar|(?:keep|stor\w*|sav\w*) .{0,30}(?:carrots|root (?:crops|vegetables)|turnips|potatoes) .{0,45}(?:winter|cold months|without .{0,8}(?:fridge|refrigerat\w*))|root (?:crops|vegetables) .{0,30}cold months)\b/,
      'root cellar|root vegetable storage|storing root crops|vegetable storage|store carrots'],
    ['', /\b(?:drafty .{0,15}(?:cabin|room|house|home)|insulat\w* .{0,22}(?:cabin|house|walls|home)|keep .{0,20}cabin warm)\b/,
      'weatherization|air sealing|building insulation|wall insulation|draft proofing|thermal insulation'],
    ['', /\b(?:bottom numbers|adding fractions|add\w* .{0,18}fractions|unlike denominators)\b/,
      'adding fractions|unlike denominators|common denominator|addition of fractions'],
    ['', /\b(?:long subtraction|subtraction with borrowing)\b/,
      'subtraction with regrouping|subtraction with borrowing|subtraction|place value'],
    ['', /\b(?:bicycl\w*|bike)\b.*\b(?:puncture|flat|inner tube)\b|\b(?:puncture|flat|inner tube)\b.*\b(?:bicycl\w*|bike)\b/,
      'bicycle puncture|bicycle flat tire|patch inner tube|inner tube repair|bicycle tire|bicycle maintenance|puncture repair kit',
      /\b(?:bicycle|bike|cycling)\b.*\b(?:tires?|tyres?|tubes?|puncture|maintenance|repair)\b|\b(?:inner tube|puncture repair|bicycle tire)\b/],
    ['', /\b(?:(?:causes?|why (?:do|are|are there)|why we have) (?:\w+ ){0,5}seasons?|seasons? (?:change|happen|occur))\b/,
      'earth seasons|seasons|season|axial tilt|tilt of the earth|earth orbit|seasonal changes|solstice|equinox',
      /^(?:[0-9 ]+ )?(?:the )?(?:earth s )?seasons?(?: on earth)?(?: page [0-9]+)?$|\b(?:axial tilt|tilt of the earth|seasons on earth|solstice|equinox)\b/],
    ['', /^(?!.*\b(?:throttle|starts?|stops?|stalls?|dies|misfire|repair|troubleshoot)\b).*\b(?:(?:car|automobile|combustion|gasoline|petrol|diesel|four stroke) engines?|engine in (?:a )?car)\b/,
      'internal combustion engine|four stroke engine|spark ignition|reciprocating engine|engine operation',
      /\b(?:internal combustion|four stroke|two stroke|spark ignition|reciprocating|petrol|diesel|gasoline) engines?\b|^(?:car|automobile) engines?$/],
    ['', /\b(?:sound out|sounding out|phonics|decod\w* .{0,10}words)\b/,
      'phonics|phonemic awareness|word decoding|beginning reading'],
    ['', /\b(?:sweat .{0,20}(?:dries|drying|evaporat\w*)|evaporative cooling)\b/,
      'evaporative cooling|evaporation|latent heat'],
    ['', /\b(?:plants? .{0,20}grow\w* .{0,20}(?:light|window)|phototropism)\b/,
      'phototropism|plant tropisms|plant growth toward light'],
    ['', /\b(?:slanted side .{0,18}right triangle|hypotenuse|pythagorean)\b/,
      'pythagorean theorem|hypotenuse|right triangle'],
    ['', /\b(?:income and expenses|money (?:earned|spent)|bookkeeping)\b/,
      'bookkeeping|cash book|income and expenses|household budget'],
    ['', /\b(?:contour lines?|contour spacing)\b/,
      'contour lines|contour intervals|topographic maps'],
    ['', /\b(?:count\w* .{0,18}steps|pace counting)\b/,
      'pace counting|land navigation|measure distance by pacing'],
    ['', /\b(?:ferment\w* .{0,30}cabbage|sauerkraut)\b/,
      'sauerkraut|fermented cabbage|lactic acid fermentation'],
    ['', /\b(?:cann\w* .{0,18}green beans|jars? of green beans|pressure canning)\b/,
      'pressure canning|canning green beans|low acid vegetables'],
    ['', /\b(?:hand sew\w*|(?:sew\w*|stitch\w*|join\w*) .{0,24}(?:cloth|fabric|seams?)|(?:cloth|fabric|seams?) .{0,18}by hand)\b/,
      'hand sewing|hand stitching|sewing stitches|sewing seams|sewing'],
    ['', /\b(?:darn\w*|(?:mend\w*|repair\w*|patch\w*) .{0,30}(?:garments?|knitwear|sweaters?|jumpers?|socks?|clothing))\b/,
      'darning|mending clothes|repair knitwear|clothing repair'],
    ['', /\b(?:wire .{0,14}broken .{0,18}meter|continuity test)\b/,
      'continuity test|multimeter|open circuit|electrical continuity'],
    ['', /\b(?:sand (?:filter|filtration)|(?:filter|purify)\w* .{0,45}(?:sand|gravel))\b/,
      'slow sand filter|sand filtration|biosand filter|sand water filter'],
    ['', /\b(?:mosquito\w* .{0,25}(?:bit\w*|repell\w*|nets?)|repel\w* .{0,18}(?:mosquito\w*|insects?)|prevent\w* .{0,21}mosquito)\b/,
      'mosquito bites|insect repellent|mosquito net|mosquito control|insect bites'],
    ['', /\b(?:join\w* .{0,20}(?:wood|boards?)|wood (?:joinery|joints?)|(?:dovetail|mortise|tenon)\w*)\b/,
      'wood joinery|wood joints|mortise and tenon|dovetail joint|woodworking joint'],
    ['', /\b(?:dry toilets?|pit (?:privy|latrine)|(?:toilet|latrine) .{0,35}(?:no sewer|without (?:water|plumbing)|no running water))\b/,
      'dry toilet|pit latrine|composting toilet|sanitation without sewer'],
    ['', /\b(?:roof (?:pitch|slope|angle)|(?:pitch|slope|angle) .{0,12}roof)\b/,
      'roof pitch|roof slope|setting rafters|rise and run|roof framing'],
    ['', /\b(?:draft\w* .{0,14}(?:door|window)|(?:seal|insulat)\w* .{0,25}(?:door|window)|weather ?stripp\w*)\b/,
      'weatherstripping|air sealing|draft proofing|door seal'],
    ['', /\b(?:primary sources?|firsthand (?:account|evidence|record))\b/,
      'primary source|firsthand account|historical sources'],
    ['', /\b(?:loose stools|fluid loss .{0,12}(?:diarrh|vomit))\b/,
      'oral rehydration|rehydration drink|dehydration|diarrhea|diarrhoea'],
    ['', /\b(?:antibiotic\w* .{0,24}(?:dos\w*|course|prescri\w*)|(?:dos\w*|prescri\w*) .{0,18}antibiotic)\b/,
      'antibiotic dosage|antibiotic therapy|antibiotic treatment|antimicrobial prescribing'],
    ['', /\b(?:sharpen\w* .{0,24}(?:ax|axe|hatchet)|(?:ax|axe|hatchet) .{0,18}(?:sharpen|grind)\w*)\b/,
      'sharpen an axe|axe sharpening|sharpen tools|grinding tools'],
  ].map(([domain, trigger, aliases, titlePattern]) => {
    const phrases = aliases.split('|');
    return {domain, trigger, canonical: phrases[0], phrases, evidence: phrases.map(terms), titlePattern};
  });

  const wrappers = /\b(?:getting started(?: with)?|how (?:to|do (?:i|we|you)|can (?:i|we|you))|what (?:can|should) (?:i|we) do|explain(?:ed)? (?:it )?simply|in (?:plain|simple) (?:english|words|terms)|step by step)\b/g;
  const child = /\b(?:bab(?:y|ies)|infants?|newborns?|toddlers?|children|child)\b/;
  const symptom = /\b(?:ill(?:ness)?|sick(?:ness(?:es)?)?|fever\w*|cough\w*|rash|vomit\w*|throw\w* up|chok\w*|dehydrat\w*|diarrh\w*|breathing|seizures?|letharg\w*|unresponsive|not eating)\b/;
  const maternity = /\b(?:childbirth|labou?r and (?:birth|delivery)|stages? (?:[1-4] )?of labou?r|birth of the placenta|obstetric delivery|pushing stage)\b/;
  const deliveryEvidence = ['stages of labor', 'stages of labour', 'labor contractions', 'labour contractions',
    'cervix dilation', 'birth of the placenta', 'deliver the placenta'].map(terms);
  const deliveryTerms = [...new Set(deliveryEvidence.flat())];
  const audiences = /\b(?:for (?:young )?(?:the )?(?:kids|children|beginners|novices|a beginner|a novice|a (?:young )?learner)|at (?:a )?beginner level|(?:show|teach|explain to) (?:a |my )?(?:child|kid|beginner))\b/g;
  const languages = 'arabic bengali chinese czech danish dutch english farsi finnish french german greek hebrew hindi hungarian indonesian italian japanese korean mandarin norwegian persian polish portuguese romanian russian spanish swahili swedish tagalog thai turkish ukrainian urdu vietnamese'.split(' ');
  const languageIntent = /\b(?:phrasebook|phrases?|expressions|vocabulary|translate|translation|(?:say|ask|speak) .{0,55} in|(?:learn|learning)(?: to speak)?)\b/;
  const phraseReference = /\b(?:phrasebook|phrase book|language learners|phrases|vocabulary|conversation|basics of|speak)\b/;
  const seedIntent = /\b(?:sav\w*|collect\w*|harvest\w*|stor\w*|dry\w*) (?:\w+ ){0,4}seeds?\b|\b(?:grow\w*|plant\w*|sow\w*)\b.*\b(?:next (?:year|season)|seeds?)\b.*\b(?:seed\w*|harvest\w*)\b/;
  const seedEvidence = ['seed saving', 'saving seed', 'seed collection', 'harvesting seeds', 'seed storage',
    'seed production', 'seed viability'].map(terms);
  const queryStop = new Set('about also am been being but can could did find get gives got have help here into just like make me my need now onto out people person please should show so some someone something take tell than that them then there these they this those through up us want was way we were which while who why will would'.split(' '));

  function prepareQuery(text, encodeQuery) {
    const original = normalize(text);
    if (new Set(words(original).filter(word => word.length > 1)).size > 32)
      throw Error('Use at most 32 different search words.');
    const audience = original.replace(audiences, '') !== original || /^getting started\b/.test(original);
    const cleaned = normalize(original.replace(wrappers, ' ').replace(audiences, ' '));
    const phrase = cleaned || original;
    const matching = rules.filter(rule => rule.trigger.test(phrase));
    const postpartum = matching.some(rule => rule.canonical === 'postpartum hemorrhage');
    const focused = postpartum ? matching.filter(rule => !maternity.test(rule.canonical)) : matching;
    const emergency = focused.some(rule => rule.domain);
    const titlePatterns = focused.filter(rule => rule.titlePattern).map(rule => rule.titlePattern);
    const deliveryQuery = focused.some(rule => maternity.test(rule.canonical));
    const pediatricHealth = !deliveryQuery && child.test(phrase) && symptom.test(phrase);
    const queryWords = words(phrase);
    const core = terms(queryWords.filter(word => !queryStop.has(word)).join(' '));
    const query = core.length ? core : terms(phrase);
    const language = languageIntent.test(phrase) && languages.find(name => queryWords.includes(name));
    const seed = seedIntent.test(phrase);
    const evidence = focused.flatMap(rule => rule.evidence);
    if (language) evidence.push(terms(language + ' phrasebook'), terms(language + ' phrases'));
    if (seed) evidence.push(...seedEvidence);
    const primary = new Set(query);
    const routing = [...new Set([...query, ...evidence.flat()])];
    const vector = query.length && encodeQuery(emergency ?
      focused.filter(rule => rule.domain).map(rule => rule.canonical).join(' ') :
      seed ? 'seed saving ' + phrase : language ? language + ' phrasebook ' + phrase :
      titlePatterns.length ? focused.find(rule => rule.titlePattern).canonical : phrase);
    return {original, phrase, query, primary, routing, focused, evidence, titlePatterns, emergency, deliveryQuery, postpartum, pediatricHealth, language, seed, audience, vector};
  }

  function hashTerm(word) {
    let value = 2166136261;
    for (let index = 0; index < word.length; index++) value = Math.imul(value ^ word.charCodeAt(index), 16777619);
    return value >>> 0;
  }

  function pairHash(left, right) {
    return Math.imul(Math.min(left, right) ^ 0x5bd1e995, Math.max(left, right) | 1) >>> 0;
  }

  function routeHits(bits, query) {
    const mask = bits.length * 8 - 1;
    let hits = 0;
    for (const word of query) {
      const key = hashTerm(word);
      if ([key & mask, (key >>> 16) & mask].every(bit => bits.charCodeAt(bit >>> 3) & (1 << (bit & 7)))) hits++;
    }
    return hits;
  }

  const semanticPart = part => part.semantic_vectors > 0;

  function bytes(encoded) {
    if (Uint8Array.fromBase64) return Uint8Array.fromBase64(encoded);
    const decoded = atob(encoded), data = new Uint8Array(decoded.length);
    for (let index = 0; index < data.length; index++) data[index] = decoded.charCodeAt(index);
    return data;
  }

  function model(table, chunks) {
    const vocab = new Map(table.vocab.map((word, index) => [word, index]));
    const dim = table.dimensions, size = vocab.size * dim;
    if (table.version !== 2 || dim !== 256 || table.scales.length !== dim ||
        chunks.reduce((sum, chunk) => sum + chunk.length, 0) !== size) throw Error('Invalid search model');
    const signed = new Int8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      signed.set(new Int8Array(chunk.buffer, chunk.byteOffset, chunk.length), offset);
      offset += chunk.length;
    }
    return text => {
      const normalized = text.slice(0, 4096).toLowerCase().normalize('NFD').replace(/\p{Mn}/gu, '');
      const vector = new Float64Array(dim);
      for (const word of normalized.match(/[\p{L}\p{N}]+/gu) || []) {
        if (word.length > 100) continue;
        const ids = [];
        for (let start = 0; start < word.length;) {
          let end = word.length, id;
          while (end > start) {
            id = vocab.get((start ? '##' : '') + word.slice(start, end));
            if (id !== undefined) break;
            end--;
          }
          if (end === start) { ids.length = 0; break; }
          ids.push(id);
          start = end;
        }
        for (const id of ids) {
          for (let col = 0; col < dim; col++) vector[col] += signed[id * dim + col];
        }
      }
      for (let col = 0; col < dim; col++) vector[col] *= table.scales[col];
      return binaryQuery(vector);
    };
  }

  const bitCount = Uint8Array.from({length: 256}, (_, number) => {
    let count = 0;
    for (; number; number &= number - 1) count++;
    return count;
  });

  function binaryQuery(vector) {
    const norm = Math.hypot(...vector) * Math.sqrt(vector.length);
    if (!norm) return null;
    const signs = new Uint8Array(vector.length / 8);
    // Precompute the signed dot product for all values of each stored byte.
    const scores = new Float32Array(signs.length * 256);
    for (let index = 0; index < signs.length; index++) {
      const start = index * 8;
      let negative = 0;
      for (let bit = 0; bit < 8; bit++) {
        const value = vector[start + bit] / norm;
        if (value >= 0) signs[index] |= 1 << bit;
        negative -= value;
      }
      const base = index * 256;
      scores[base] = negative;
      for (let code = 1; code < 256; code++) {
        const bit = code & -code;
        const component = 31 - Math.clz32(bit);
        scores[base + code] = scores[base + code - bit] + 2 * vector[start + component] / norm;
      }
    }
    return {signs, scores};
  }

  function vectorScore(query, code, lexicalMatch) {
    if (code.length !== query.signs.length) throw Error('Search vector dimensions differ');
    if (!lexicalMatch) {
      let distance = 0;
      for (let index = 0; index < code.length; index++) distance += bitCount[code[index] ^ query.signs[index]];
      if (distance > code.length * 3.55) return 0;
    }
    let score = 0;
    for (let index = 0; index < code.length; index++) score += query.scores[index * 256 + code[index]];
    return score;
  }

  async function unpack(encoded, query) {
    const needed = query && new Set(query);
    // Stemming strips suffixes except for the ies-to-y rule. A retained
    // prefix lets a browser skip titles that cannot produce a query term.
    const prefixes = query?.map(word => word.endsWith('y') ? word.slice(0, -1) : word);
    const stream = new Blob([bytes(encoded)]).stream().pipeThrough(new DecompressionStream('gzip'));
    const chunk = await new Response(stream).json();
    chunk.vectors = [];
    chunk.semantic = [];
    chunk.vectorCache = [];
    for (const [index, row] of chunk.records.entries()) {
      if (row[0] === null) row[0] = row[1].split('/').at(-1).replace(/_/g, ' ');
      if (row[3]) {
        chunk.vectors.push(index);
        if (!row[5]) chunk.semantic.push(index);
      }
      if (row[5]) {
        if (prefixes) {
          const title = /^[\x00-\x7f]*$/.test(row[0]) ? row[0].toLowerCase() : fold(row[0]);
          if (!prefixes.some(prefix => title.includes(prefix))) continue;
        }
        for (const term of terms(row[0])) {
          if (needed && !needed.has(term)) continue;
          if (!Object.hasOwn(chunk.postings, term)) Object.defineProperty(chunk.postings, term, {value: []});
          chunk.postings[term].push(index * 16 + 9);
        }
      }
    }
    return chunk;
  }

  function filter(asset, shelf) {
    if (shelf === 'legacy') return asset.legacy;
    if (shelf !== 'all-with-legacy' && asset.legacy) return false;
    return shelf === 'all' || shelf === 'all-with-legacy' || asset.shelves.includes(shelf);
  }

  function sourcePolicy(asset) {
    const health = /^(?:medical|first[_-]aid|health|dental)$/.test(asset.category);
    const domains = [health && 'health', /^(?:shelter|preparedness|navigation)$/.test(asset.category) && 'survival',
      /^water/.test(asset.category) && 'water'];
    // Some titles are the only indicator in older composed selections.
    const discussion = asset.discussion ?? /stackexchange|stack overflow|mathoverflow|q&a/i.test(
      (asset.id + ' ' + asset.title).replace(/stack exchange/gi, 'stackexchange'));
    return {domains, discussion};
  }

  function conceptScore(weights, phrases) {
    let best = 0;
    for (const phrase of phrases) {
      let strength = 0;
      for (const word of phrase) {
        const weight = weights.get(word);
        if (!weight) { strength = 0; break; }
        strength += weight;
      }
      if (strength) best = Math.max(best, 16 + 6 * Math.min(phrase.length, 3) + 3 * strength / phrase.length);
    }
    return best;
  }

  function lookupTerms(query) {
    return query.pediatricHealth ? [...new Set([...query.routing, ...deliveryTerms])] : query.routing;
  }

  function rankPart(part, prepared, asset, limit) {
    const {query, primary, phrase, vector, focused, evidence, titlePatterns, emergency, deliveryQuery, postpartum, pediatricHealth, language, seed, audience} = prepared;
    const {domains, discussion} = sourcePolicy(asset);
    const trusted = asset.critical && focused.some(rule => domains.includes(rule.domain));
    const pediatricSource = pediatricHealth && domains.includes('health');
    const sourceTitle = emergency || audience || pediatricHealth || language || seed ? normalize(asset.title) : "";
    const lexical = new Map();
    for (const word of lookupTerms(prepared)) {
      const postings = Object.hasOwn(part.postings, word) ? part.postings[word] : [];
      const original = primary.has(word);
      for (const post of postings) {
        const index = post >>> 4, weight = post & 15;
        let stats = lexical.get(index);
        if (!stats) lexical.set(index, stats = {hits: 0, strength: 0, body: false, bodyHits: 0, leadHits: 0, weights: evidence.length || pediatricHealth ? new Map() : null});
        stats.weights?.set(word, weight);
        if (original) {
          stats.hits++;
          stats.strength += weight;
          if (weight <= 3) {
            stats.body = true;
            stats.bodyHits++;
          }
          if (weight === 3) stats.leadHits++;
        }
      }
    }
    const found = [];
    const candidates = vector && !emergency && !discussion ?
      new Set([...lexical.keys(), ...(part.semantic || part.vectors)]) : lexical.keys();
    for (const index of candidates) {
      const row = part.records[index];
      const stats = lexical.get(index);
      const support = stats?.weights ? conceptScore(stats.weights, evidence) : 0;
      if (stats && !stats.hits && !support) continue;
      let similarity = 0;
      if (vector && row[3] && !row[5]) {
        const packed = part.vectorCache ? (part.vectorCache[index] ??= bytes(row[3])) : bytes(row[3]);
        similarity = vectorScore(vector, packed, Boolean(stats));
      }
      if (!stats && similarity < 0.37) continue;
      const title = normalize(row[0]);
      const archivePath = typeof row[1] === 'string' ? row[1] : '';
      const dictionary = /(?:^English-[^/]+\/|(?:^|\/)(?:vocabulary|dictionary|glossary)\/)/i.test(archivePath);
      const conceptTitle = !dictionary && !/\/[a-z]{2,3}$/i.test(row[0]) &&
        titlePatterns.some(pattern => pattern.test(title));
      const deliverySection = deliveryQuery && trusted && asset.format === 'pdf' &&
        /\b(?:pushing|second stage|stage 2|giving good care during labor)\b/.test(title + ' ' + sourceTitle);
      const postpartumSection = postpartum &&
        /\b(?:postpartum (?:bleeding|ha?emorrhage)|birth of the placenta|bleeding after (?:birth|delivery))\b/
          .test(title + ' ' + sourceTitle);
      const exact = title === phrase || title === prepared.original;
      const phraseHit = !exact && query.length > 1 && title.includes(phrase);
      const coverage = stats ? stats.hits / query.length : 0;
      const strength = stats ? stats.strength / query.length : 0;
      const lexicalScore = coverage ? 12 + 70 * coverage ** 2 + 6 * strength : 0;
      const question = discussion;
      const answer = question && row[6] && row[2] ? terms(row[2]) : [];
      const answerHits = Math.max(stats?.leadHits || 0, answer.filter(word => primary.has(word)).length,
        row[6] && row[7] === 'Accepted answer' && stats?.body ? stats.bodyHits : 0);
      const answerConcept = support && answer.length && evidence.some(words => words.every(word => answer.includes(word)));
      const matchedAnswer = row[6] && (answerConcept ||
        answerHits >= Math.min(2, query.length) && answerHits / query.length >= 0.4);
      const passage = !row[5] && (row[2] || stats?.body || row[3] && asset.format !== 'zim');
      const typedScore = question ? matchedAnswer ? 4 : -55 : passage ? 19 : row[5] ? -12 : 0;
      const reference = title + ' ' + sourceTitle;
      const deliveryPassage = pediatricHealth && stats?.weights &&
        deliveryEvidence.some(words => words.every(word => stats.weights.has(word)));
      const maternityReference = ((emergency || pediatricHealth) && maternity.test(reference)) || deliveryPassage;
      const emergencyReference = trusted && (/\b(?:first aid|emergency care|survival)\b/.test(reference) ||
        (deliveryQuery && maternityReference));
      const readyReference = audience && /\b(?:elementary|beginners?|introduction|introductory|wikijunior|arithmetic|grade [1-6])\b/.test(reference);
      const advancedReference = audience && /\b(?:polynomial|graduate|abstract algebra|differential equations)\b/.test(reference) &&
        !/\b(?:polynomial|graduate|abstract algebra|differential equations)\b/.test(phrase);

      const titleScore = exact && (!question || matchedAnswer) ? 145 : phraseHit ? 29 : 0;
      let score = titleScore + lexicalScore +
        (coverage ? 95 : 160) * Math.max(0, similarity - 0.24) + typedScore - (row[4] ? 19 : 0);
      if (emergency) {
        score = support ? (exact && !question ? 58 : 0) + Math.min(lexicalScore, 48) + 1.65 * support +
          22 * Math.max(0, similarity - 0.30) + typedScore +
          (trusted ? 39 : 0) + (emergencyReference ? 16 : 0) +
          (deliverySection ? 52 : 0) + (postpartumSection ? 70 : 0) -
          (maternityReference && !deliveryQuery ? (pediatricHealth ? 50 : 25) : 0) +
          (pediatricSource && child.test(reference) && symptom.test(reference) ? 12 : 0) - (question ? 30 : 0) - (row[4] ? 19 : 0) :
          Math.min(score, 34);
      } else {
        score += 0.95 * support + (asset.critical && (stats?.body || similarity >= 0.43) ? 5 : 0) +
          (readyReference ? 18 : 0) - (advancedReference ? 22 : 0) +
          (conceptTitle && (!question || answerConcept) ? 130 : titlePatterns.length ? -48 : 0);
        if (language && (' ' + reference + ' ').includes(' ' + language + ' ') && phraseReference.test(reference)) score += 90;
        if (seed && support) score += Math.min(36, support / 2) * (stats?.hits ? 1 : 0.5);
        if (pediatricHealth) {
          if (maternityReference) score -= 30;
          else if (pediatricSource && child.test(reference)) score += 25;
        }
      }
      found.push({row, index, score, fullMatch: stats?.hits === query.length, focused: emergency && support > 0});
    }
    return found.sort((a, b) => b.score - a.score || a.index - b.index).slice(0, limit);
  }

  function partPriority(asset, part, query) {
    if (!query.emergency) return 0;
    const {domains} = sourcePolicy(asset);
    const onTopic = query.focused.some(rule => domains.includes(rule.domain));
    if (asset.critical && onTopic && semanticPart(part)) return asset.format === "zim" ? 3 : 4;
    if (onTopic && semanticPart(part)) return 2;
    return semanticPart(part) ? 1 : 0;
  }

  function placeholderTitle(value) {
    const title = (value || '').trim();
    return !/[\p{L}\p{N}]/u.test(title) || /^(?:page\s+)?[\p{N}.,]+$/iu.test(title) ||
      /^(?:[a-z]+:\/\/|[a-z]:\\|[./\\]*[a-z0-9_.%+-]+[/\\][^\s]+$)|\.(?:html?|pdf|docx?|xlsx?|pptx?|jpe?g|png|gif|zip|txt|php|aspx?|epub|djvu|swf)$/iu.test(title);
  }

  function displayTitle(asset, rawTitle, locator) {
    const override = asset.title_overrides;
    const title = (override && Object.hasOwn(override, locator) ? override[locator] : rawTitle) || '';
    const sourceTitle = placeholderTitle(asset.title) ? 'Library reference' : asset.title;
    if (asset.format === 'pdf' && (asset.restricted || placeholderTitle(title))) {
      const heading = title.replace(/(?:^| · )Page \d+$/i, '');
      const outline = asset.entrypoints?.findLast(([page, name]) => typeof page === 'number' &&
        page <= locator && !placeholderTitle(name))?.[1].replace(/ · Page \d+$/i, '');
      const section = placeholderTitle(heading) ? outline : heading;
      return [sourceTitle, section && section !== sourceTitle ? section : '', 'Page ' + locator].filter(Boolean).join(' · ');
    }
    if (!placeholderTitle(title)) return title;
    // A numeric entry may name a year, quantity or numbered section.
    const number = title.trim().match(/^[\p{N}.,]+$/u)?.[0];
    return sourceTitle + (number ? ' · Entry ' + number : asset.format === 'zim' ? ' · Archive entry' : ' · Section');
  }

  function result(asset, hit, part) {
    const [rawTitle, locator, lead, , , , , heading] = hit.row;
    const title = displayTitle(asset, rawTitle, locator);
    const archive = asset.format === 'zim';
    const destination = asset.destination;
    const href = destination.split('/').map(encodeURIComponent).join('/') +
      (asset.format === 'pdf' ? '#page=' + locator :
        !archive && locator ? '#' + encodeURIComponent(locator) : '');
    return {score: hit.score, rankTitle: rawTitle, fullMatch: hit.fullMatch, focused: hit.focused, indexed: true, record: {id: asset.id + ':' + part + ':' + hit.index,
      asset_id: asset.id, title, description: lead, source_title: asset.title, href, destination,
      kind: archive ? 'article' : 'section', reader_required: archive,
      location: archive ? 'Archive path: ' + locator + (heading ? ' · ' + heading : '') : asset.format === 'pdf' ? 'Page ' + locator :
        locator ? 'Section: ' + locator : 'HTML',
      license: asset.license, attribution: asset.attribution}};
  }

  const READ_BUDGET = 28_000_000;
  const BOUNDED_BYTES = 39_700_000;
  const TERM_BYTES = 4_000_000;

  function impactBucket(word) {
    return (hashTerm(word) >>> 24).toString(16).padStart(2, '0') + '.js';
  }

  async function impactBlock(packed) {
    const stream = new Blob([bytes(packed)]).stream().pipeThrough(new DecompressionStream('gzip'));
    const raw = new Uint8Array(await new Response(stream).arrayBuffer());
    const decoder = new TextDecoder('utf-8', {fatal: true});
    const dictionary = new Map();
    const cursor = {offset: 0};
    while (cursor.offset < raw.length) {
      const length = unsigned(raw, cursor);
      const posts = unsigned(raw, cursor);
      const df = unsigned(raw, cursor);
      const start = cursor.offset;
      if (!length || !posts || !df || start + length + posts > raw.length) throw Error('Invalid term block');
      const term = decoder.decode(raw.subarray(start, start + length));
      cursor.offset = start + length + posts;
      dictionary.set(term, {data: raw.subarray(start + length, cursor.offset), df});
    }
    return dictionary;
  }

  function unsigned(raw, cursor) {
    let value = 0, shift = 0;
    while (cursor.offset < raw.length && shift <= 28) {
      const octet = raw[cursor.offset++];
      value += (octet & 127) * 2 ** shift;
      if (!(octet & 128)) return value;
      shift += 7;
    }
    throw Error('Invalid impact integer');
  }

  function* impactPostings(raw) {
    const cursor = {offset: 0};
    let lastImpact = 16;
    while (cursor.offset < raw.length) {
      const impact = unsigned(raw, cursor);
      const count = unsigned(raw, cursor);
      if (!impact || impact >= lastImpact || !count || count > 32) throw Error('Invalid impact band');
      lastImpact = impact;
      let id = 0;
      for (let i = 0; i < count; i++) {
        const delta = unsigned(raw, cursor);
        if (!delta) throw Error('Invalid impact part address');
        id += delta;
        yield [id, impact];
      }
    }
  }

  async function impactEvidence(query, files, read) {
    const words = lookupTerms(query);
    const grouped = new Map();
    let remaining = TERM_BYTES;
    for (const term of words) {
      const bucket = impactBucket(term);
      if (!Object.hasOwn(files, bucket)) continue;
      if (!grouped.has(bucket)) {
        const size = files[bucket];
        if (size > remaining) continue;
        remaining -= size;
        grouped.set(bucket, []);
      }
      grouped.get(bucket).push(term);
    }
    const blocks = await Promise.all([...grouped].map(async ([bucket, terms]) =>
      [terms, await read(bucket)]));
    const hits = new Map(), weightByWord = new Map();
    for (const [terms, block] of blocks) {
      for (const term of terms) {
        const row = block.get(term);
        if (!row) continue;
        // Part frequency is computed before truncating common term bands.
        const rarity = 1 + Math.max(0, Math.log2(600 / (row.df + 1))) / 3;
        weightByWord.set(term, rarity);
        for (const [id, impact] of impactPostings(row.data)) {
          const values = hits.get(id) || new Map();
          values.set(term, impact);
          hits.set(id, values);
        }
      }
    }
    return {hits, weightByWord, readBytes: TERM_BYTES - remaining};
  }

  function impactPriority(index, id, query) {
    const terms = index?.hits.get(id);
    if (!terms) return 0;
    let total = 0, present = 0;
    for (const term of query.query) {
      const weight = terms.get(term);
      if (weight) {
        present++;
        total += weight * index.weightByWord.get(term);
      }
    }
    const support = query.evidence.reduce((best, phrase) => {
      let score = 0;
      for (const term of phrase) {
        if (!terms.has(term)) return best;
        score += terms.get(term);
      }
      return Math.max(best, score / phrase.length);
    }, 0);
    return (1.4 * total + 16 * present) / (6 + query.query.length) +
      support * (query.emergency ? 1.4 : 0.65);
  }
  const decoded = new WeakMap();

  function rankedQueue(selection, query, shelf = 'all', budget = Infinity, evidence) {
    const queue = [];
    const exact = [query.phrase, query.original].map(title => hashTerm('^' + title));
    const concepts = query.focused.filter(rule => rule.titlePattern)
      .flatMap(rule => rule.phrases).map(title => hashTerm('^' + title));
    const pairs = [];
    for (const terms of [query.query, ...query.evidence]) {
      const keys = terms.map(hashTerm);
      for (let left = 0; left < keys.length; left++)
        for (let right = left + 1; right < keys.length; right++) pairs.push(pairHash(keys[left], keys[right]));
    }
    let routed = false;
    for (const asset of selection.sources) {
      if (!filter(asset, shelf)) continue;
      const discussion = sourcePolicy(asset).discussion;
      const sourceQueue = [];
      for (const [number, part] of asset.parts.entries()) {
        let data = decoded.get(part);
        if (!data) {
          data = {bloom: atob(part.bloom), lexical: part.route && bytes(part.route[0]),
            centroids: part.route?.[1] ? bytes(part.route[1]) : null};
          decoded.set(part, data);
        }
        const hits = routeHits(data.bloom, query.routing);
        if (!hits && !evidence?.hits.has(part.impact) && (!query.vector || query.emergency || discussion || !semanticPart(part))) continue;
        const priority = partPriority(asset, part, query);
        let score = priority + hits;
        if (data.lexical) {
          routed = true;
          const mask = data.lexical.length * 8 - 1;
          const matches = key => [key & mask, (key >>> 15) & mask].every(bit =>
            data.lexical[bit >>> 3] & (1 << (bit & 7)));
          const exactMatch = exact.some(matches);
          const conceptMatch = concepts.some(matches);
          const pairStrength = pairs.filter(matches).length;
          const primaryHits = routeHits(data.bloom, query.query);
          let affinity = 0;
          if (query.vector && !query.emergency && !discussion && data.centroids)
            for (let offset = 0; offset < data.centroids.length; offset += 32)
              affinity = Math.max(affinity, vectorScore(query.vector, data.centroids.subarray(offset, offset + 32), true));
          const small = part.bytes < 200_000;
          score = 6 * priority + 3.5 * primaryHits / query.query.length +
            (exactMatch ? 3 : 0) + (conceptMatch ? 4 : 0) + 2.5 * Math.log1p(pairStrength) +
            12 * Math.max(0, affinity - 0.17) + (asset.format === 'pdf' ? 3 : 0) +
            (asset.critical ? 1 : 0) + (small ? 1 : 0) - (discussion && semanticPart(part) ? 1 : discussion ? 4 : 0);
        }
        const heuristic = score;
        if (evidence) {
          const lexical = impactPriority(evidence, part.impact, query);
          score = score * 0.65 + lexical;
          if (!semanticPart(part) && asset.format === 'zim' && hits > 1) score += 0.7;
        }
        sourceQueue.push({asset, number, hits, priority, score, heuristic});
      }
      const ranked = [...sourceQueue].sort((a, b) => b.score - a.score || b.hits - a.hits);
      for (const [index, item] of ranked.entries()) {
        item.score -= Math.log2(1 + index) * (asset.critical ? 0.45 : 1.4);
      }
      queue.push(...sourceQueue);
    }
    queue.sort((a, b) => (routed ? b.score - a.score : b.priority - a.priority) || b.hits - a.hits);
    if (evidence && Number.isFinite(budget)) {
      // Share the read allowance between complementary signals. In particular,
      // small chapters must compete with large encyclopedias for term density.
      const selected = new Map();
      function add(lane, allowance) {
        for (const item of lane) {
          const {asset, number} = item;
          const key = partAddress(asset, number);
          if (selected.has(key)) continue;
          const size = asset.parts[number].bytes || 200_000;
          if (size > allowance) continue;
          selected.set(key, item);
          allowance -= size;
        }
        return allowance;
      }
      const head = budget * 0.58;
      let available = budget - head + add(queue, head);
      const small = queue.filter(({asset, number}) =>
        (asset.format !== 'zim' || asset.parts.length <= 4) && semanticPart(asset.parts[number]));
      const reference = budget * 0.20;
      available = available - reference + add(small, reference);
      const fallback = [...queue].sort((a, b) => b.heuristic - a.heuristic || b.score - a.score);
      add(fallback, available);
      return queue.filter(({asset, number}) => selected.has(partAddress(asset, number)));
    }
    const charged = new Set();
    let remaining = budget;
    return queue.filter(({asset, number}) => {
      const part = asset.parts[number];
      const key = partAddress(asset, number);
      if (charged.has(key)) return true;
      const size = part.bytes || 200_000;
      if (size > remaining) return false;
      charged.add(key);
      remaining -= size;
      return true;
    });
  }

  function partAddress(asset, number) {
    const part = asset.parts[number];
    return part.path || (part.pool || asset.sha256) + ':' + (part.number ?? number);
  }

  async function search(selection, encodeQuery, readPart, text, shelf = 'all', limit = 30,
                        cancelled = () => false, onProgress, budget = Infinity, readImpact, complete = false) {
    const query = prepareQuery(text, encodeQuery);
    if (!query.query.length || cancelled()) return [];
    const evidence = readImpact && selection.impact ? await impactEvidence(query, selection.impact, readImpact) : null;
    if (cancelled()) return [];
    const queue = rankedQueue(selection, query, shelf, budget - (evidence?.readBytes || 0), evidence);
    const firstPass = queue.length;
    if (complete && Number.isFinite(budget)) {
      const identity = ({asset, number}) => `${asset.id}:${number}`;
      const selected = new Set(queue.map(identity));
      queue.push(...rankedQueue(selection, query, shelf).filter(item => !selected.has(identity(item))));
    }
    const multiple = new Map();
    for (const {asset, number} of queue) {
      const key = partAddress(asset, number);
      multiple.set(key, (multiple.get(key) || 0) + 1);
    }
    const shared = new Map();
    const matches = [];
    const queryTerms = lookupTerms(query);
    let updatedAt = -Infinity;
    for (const [position, {asset, number}] of queue.entries()) {
      if (position === firstPass) onProgress?.(topResults(matches, limit), 'refining');
      if (cancelled()) return [];
      const part = asset.parts[number];
      const address = partAddress(asset, number);
      const chunk = shared.get(address) ?? await readPart(part.pool || asset.sha256, part.number ?? number,
        queryTerms, part.path);
      const left = multiple.get(address) - 1;
      multiple.set(address, left);
      if (left) shared.set(address, chunk);
      else shared.delete(address);
      if (cancelled()) return [];
      const hits = rankPart(chunk, query, asset, limit);
      if (!hits.length) continue;
      matches.push(...hits.map(hit => result(asset, hit, number)));
      retainCandidates(matches, limit * 4);
      if (position < firstPass && onProgress && performance.now() - updatedAt >= 150) {
        onProgress(topResults(matches, limit), 'indexed');
        updatedAt = performance.now();
      }
    }
    return topResults(matches, limit);
  }

  const order = (a, b) => b.score - a.score || (a.rankTitle || a.record.title).localeCompare(b.rankTitle || b.record.title, 'en') ||
    a.record.id.localeCompare(b.record.id, 'en');

  const fullPassage = hit => hit.fullMatch && hit.record.kind === 'section';

  function retainCandidates(matches, limit) {
    matches.sort(order);
    if (matches.length > limit) {
      const passages = matches.slice(limit).filter(fullPassage).slice(0, limit / 4);
      matches.splice(limit, matches.length, ...passages);
    }
  }

  function topResults(matches, limit) {
    const seen = new Set(), perSource = new Map();
    const first = [], later = [];
    for (const hit of matches.sort(order)) {
      const {record} = hit;
      // Preserve distinct locations and collapse equivalent spellings within an archive.
      const key = record.asset_id + '\0' + (record.kind === 'article' ? normalize(hit.rankTitle || record.location) : record.href);
      if (seen.has(key)) continue;
      seen.add(key);
      const count = perSource.get(record.asset_id) || 0;
      perSource.set(record.asset_id, count + 1);
      (count < 3 ? first : later).push(hit);
    }
    const [best, second, third, ...other] = first;
    const head = [best, second, third].filter(Boolean);
    const pageHits = other.filter(fullPassage);
    let passages = pageHits.slice(0, 3);
    // A reference can have many pages with identical term scores. Let
    // different books with that score surface before its repeated pages.
    if (passages.length === 3 && passages[0].score === passages[2].score &&
        new Set(passages.map(hit => hit.record.asset_id)).size < 3 && !first.some(hit => hit.focused)) {
      const represented = new Set();
      const tied = pageHits.filter(hit => {
        const id = hit.record.asset_id;
        if (hit.score !== passages[0].score || represented.has(id)) return false;
        represented.add(id);
        return true;
      });
      if (tied.length >= 3) passages = tied.slice(0, 4);
    }
    const promoted = new Set(passages);
    return [...head, ...passages, ...other.filter(hit => !promoted.has(hit)), ...later].slice(0, limit);
  }

  function classic(script, selection, table, run = search) {
    if (selection.version !== 1 || !Array.isArray(selection.sources)) throw Error('Invalid search selection');
    let ready;
    const loadModel = () => ready ??= (async () => {
      const count = selection.model_parts;
      if (!Number.isInteger(count) || count < 1 || count > 32) throw Error('Invalid search model parts');
      const chunks = [];
      root.OWLModelWeights = ([number, encoded]) => {
        if (Number.isInteger(number) && number >= 0 && number < count) chunks[number] = bytes(encoded);
      };
      try {
        // Await all loads before clearing the callback, including on a failed load.
        const loaded = await Promise.allSettled(Array.from({length: count}, (_, index) =>
          script('SEARCH/model/' + String(index).padStart(2, '0') + '.js')));
        if (loaded.some(result => result.status === 'rejected') || chunks.filter(Boolean).length !== count)
          throw Error('The local search model could not load.');
        return model(table, chunks);
      } finally {
        delete root.OWLModelWeights;
      }
    })().catch(() => {
      ready = undefined;
      return () => null;
    });
    // Each page owns one script callback at a time. New searches can cancel reads
    // between chunks, so they cannot replace callbacks for an active script.
    let queue = Promise.resolve();
    const readPart = (digest, number, query, path) => {
      if (path && !/^chunks\/[a-f0-9]{64}\.js$/.test(path)) return Promise.reject(Error('Invalid search chunk path'));
      if (!/^[a-f0-9]{64}$/.test(digest) || !Number.isInteger(number) || number < 0 || number >= 100000)
        return Promise.reject(Error('Invalid search shard'));
      const task = queue.then(async () => {
        let data;
        const callback = path ? 'OWLShardBlob' : 'OWLShardPart';
        root[callback] = value => { data = value; };
        try {
          await script('SEARCH/' + (path || 'sources/' + digest + '/' + String(number).padStart(5, '0') + '.js'));
          if (path) {
            if (typeof data !== 'string') throw Error('Search chunk could not load');
            return await unpack(data, query);
          }
          if (!data || data[0] !== digest || data[1] !== number) throw Error('Search shard identity differs');
          return await unpack(data[2], query);
        } finally {
          delete root[callback];
        }
      });
      queue = task.catch(() => {});
      return task;
    };
    const cache = new Map();
    function readImpact(path) {
      if (!/^[a-f0-9]{2}\.js$/.test(path)) return Promise.reject(Error('Invalid term bucket'));
      if (cache.has(path)) return cache.get(path);
      const task = queue.then(async () => {
        let data;
        root.OWLImpactBlock = value => { data = value; };
        try {
          await script('SEARCH/impact/' + path);
          if (typeof data !== 'string') throw Error('Term bucket could not load');
          return await impactBlock(data);
        } finally {
          delete root.OWLImpactBlock;
        }
      });
      queue = task.catch(() => {});
      cache.set(path, task);
      task.catch(() => { if (cache.get(path) === task) cache.delete(path); });
      if (cache.size > 24) cache.delete(cache.keys().next().value);
      return task;
    }
    return async (text, shelf, limit, cancelled, onProgress) =>
      run(selection, await loadModel(), readPart, text, shelf, limit, cancelled, onProgress,
        selection.impact ? BOUNDED_BYTES : Infinity,
        selection.impact ? readImpact : undefined, true);
  }

  const api = {classic, model, binaryQuery, bytes, search, terms, prepareQuery, unpack, rankPart, normalize, result,
    retainCandidates, topResults, lookupTerms, filter, vectorScore, placeholderTitle, displayTitle,
    hashTerm, pairHash, rankedQueue, impactPostings, impactBlock, impactEvidence,
    readBudget: READ_BUDGET, boundedBytes: BOUNDED_BYTES};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OWLShardRank = api;
})(globalThis);
