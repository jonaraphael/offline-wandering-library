/* Offline ranking over independently packed, selected source shards. */
(function (root) {
  'use strict';
  const stop = new Set('a an and are as at be by do does for from how i in is it of on or the to use what when where with you your'.split(' '));
  const fold = text => text.toLowerCase().normalize('NFKD').replace(/\p{M}/gu, '');
  const words = text => fold(text).match(/[\p{L}\p{N}]+/gu) || [];
  const normalize = text => words(text).join(' ');
  const suffixes = ['ing', 'ed', 'es', 's'];

  function stem(word) {
    if (word.length > 4 && word.endsWith('ies')) return word.slice(0, -3) + 'y';
    if (word.length > 5 && word.endsWith('oes')) return word.slice(0, -2);
    for (const suffix of suffixes) {
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
    ['health', /\b(?:anaphylax\w*|severe allergic reaction|throat .{0,12}swell\w*|epipen|hives .{0,18}(?:cannot|can t) breathe)\b/,
      'anaphylaxis|anaphylactic shock|severe allergic reaction|epinephrine|adrenaline autoinjector',
      /\b(?:anaphylax\w*|anaphylactic shock|severe allergic reaction)\b/],
    ['health', /\b(?:heart attack|myocardial infarction|chest (?:pain|pressure|tightness) .{0,40}(?:arm|jaw|sweat\w*))\b/,
      'heart attack|myocardial infarction|acute coronary syndrome|chest pain',
      /\b(?:heart attack|myocardial infarction|acute coronary syndrome)\b/],
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
    ['health', /\b(?:(?:signs?|symptoms?|recogniz\w*|assess\w*) (?:\w+ ){0,3}dehydration|dehydration (?:signs?|symptoms?|assessment))\b/,
      'dehydration signs|dehydration assessment|dehydration|oral rehydration',
      /\b(?:dehydration|oral rehydration)\b/],
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
      'bicycle puncture|bicycle flat tire|bicycle tire inner tube replacement|patching a bicycle tire inner tube|patch inner tube|inner tube repair|bicycle tire|bicycle maintenance|puncture repair kit',
      /\b(?:bicycle|bike|cycling)\b.*\b(?:tires?|tyres?|tubes?|puncture|maintenance|repair)\b|\b(?:inner tube|puncture repair|bicycle tire)\b/],
    ['', /\b(?:(?:causes?|why (?:do|are|are there)|why we have) (?:\w+ ){0,5}seasons?|seasons? (?:change|happen|occur))\b/,
      'earth seasons|seasons|season|axial tilt|tilt of the earth|earth orbit|seasonal changes|solstice|equinox',
      /^(?:[0-9 ]+ )?(?:the )?(?:earth s )?seasons?(?: on earth)?(?: page [0-9]+)?$|\b(?:axial tilt|tilt of the earth|seasons on earth|solstice|equinox)\b/],
    ['', /^(?!.*\b(?:throttle|starts?|stops?|stalls?|dies|misfire|repair|troubleshoot)\b).*\b(?:(?:car|automobile|combustion|gasoline|petrol|diesel|four stroke) engines?|engine in (?:a )?car)\b/,
      'internal combustion engine|four stroke engine|spark ignition|reciprocating engine|engine operation',
      /\b(?:internal combustion|four stroke|two stroke|spark ignition|reciprocating|petrol|diesel|gasoline) engines?\b|^(?:car|automobile) engines?$/],
    ['', /\b(?:sound out|sounding out|phonics|decod\w* .{0,10}words)\b/,
      'phonics|phonemic awareness|word decoding|beginning reading'],
    ['', /\b(?:sweat .{0,20}(?:dries|drying|evaporat\w*)|evaporative cooling|water .{0,16}vapou?r)\b/,
      'evaporation|evaporative cooling|vaporization|latent heat',
      /\b(?:evaporat\w*|vapori[sz]ation|evaporative cooling)\b/],
    ['', /\b(?:plants? .{0,20}grow\w* .{0,20}(?:light|window)|phototropism)\b/,
      'phototropism|plant tropisms|plant growth toward light'],
    ['', /\b(?:slanted side .{0,18}right triangle|hypotenuse|pythagorean)\b/,
      'pythagorean theorem|hypotenuse|right triangle', /\b(?:pythagorean theorem|right triangle)\b/],
    ['', /\b(?:income and expenses|money (?:earned|spent)|bookkeeping)\b/,
      'bookkeeping|cash book|income and expenses|household budget'],
    ['', /\b(?:contour lines?|contour spacing|topographic maps?)\b/,
      'contour lines|contour intervals|topographic maps', /\b(?:topograph\w*|contour (?:lines?|intervals?)|map reading|land navigation)\b/],
    ['', /\b(?:count\w* .{0,18}steps|pace counting)\b/,
      'pace counting|land navigation|measure distance by pacing'],
    ['', /\b(?:ferment\w* .{0,30}cabbage|sauerkraut)\b/,
      'sauerkraut|fermented cabbage|lactic acid fermentation', /\b(?:sauerkraut|fermented and pickled foods)\b/],
    ['', /\bmilk .{0,22}spoil\w*\b/,
      'cool milk storage|refrigerate milk storage|cool milk|milk preservation|milk storage'],
    ['', /\b(?:can(?:n\w*)? .{0,18}(?:green|snap) beans|jars? of green beans|pressure canning)\b/,
      'pressure canning|canning green beans|snap and italian beans|low acid vegetables|using pressure canners',
      /\b(?:snap and italian beans|canning (?:green beans|04 vegetables)|pressure cann\w*)\b/],
    ['', /\b(?:dry\w*|dehydrat\w*) .{0,22}(?:apple|fruit)\w*\b/,
      'drying fruit|dehydrating apples|dried fruit|drying foods',
      /\b(?:drying (?:fruit|apples|foods)|dried (?:apples|fruit)|dehydrating (?:apples|fruit))\b/],
    ['', /\b(?:compost\w*|kitchen scraps .{0,25}(?:soil|pests))\b/,
      'compost|composting|compost pile', /\bcompost\w*\b/],
    ['', /\b(?:start\w*|sow\w*) .{0,18}(?:seedlings?|seeds) .{0,10}indoors\b/,
      'starting seeds indoors|seed starting|raising seedlings|using egg cartons as seed starters',
      /\b(?:start\w* .{0,16}seeds?|seed .{0,12}start\w*|seedlings? indoors)\b/],
    ['', /\bwhole (?:wheat|grain) bread\b/,
      'whole wheat bread|whole grain bread|baking bread|bread baking',
      /\b(?:whole (?:wheat|grain) bread(?! teardown)|bread.{0,15}baking|baking.{0,15}bread)\b/],
    ['', /\b(?:rainwater|rain water|rain catchment)\b/,
      'rainwater harvesting|rainwater collection|rainwater catchment', /\b(?:rainwater|rain water|rain catchment)\b/],
    ['', /\b(?:hand sew\w*|(?:sew\w*|stitch\w*|join\w*) .{0,24}(?:cloth|fabric|seams?)|(?:cloth|fabric|seams?) .{0,18}by hand)\b/,
      'hand sewing|hand stitching|sewing stitches|sewing seams|sewing'],
    ['', /\b(?:darn\w*|(?:mend\w*|repair\w*|patch\w*) .{0,30}(?:garments?|knitwear|sweaters?|jumpers?|socks?|clothing))\b/,
      'darning|mending clothes|repair knitwear|clothing repair'],
    ['', /\b(?:wire .{0,14}broken .{0,18}meter|continuity test|multimeter.*continuity)\b/,
      'continuity test|multimeter|open circuit|electrical continuity',
      /\b(?:multimeter|continuity)\b/],
    ['', /\b(?:sand (?:filter|filtration)|(?:filter|purify)\w* .{0,45}(?:sand|gravel))\b/,
      'slow sand filter|sand filter|sand filtration|biosand filter|sand water filter',
      /\b(?:slow sand|bio ?sand|sand water) filter\w*\b|\bsand filtration\b/],
    ['', /\b(?:mosquito\w* .{0,25}(?:bit\w*|repell\w*|nets?)|repel\w* .{0,18}(?:mosquito\w*|insects?)|prevent\w* .{0,21}mosquito)\b/,
      'mosquito bites|mosquito bite prevention|preventing mosquito bites|mosquito repellent|insect repellent|mosquito net|mosquito control|insect bites',
      /\b(?:mosquito(?:es)? .{0,24}(?:bites?|repell\w*)|insect repell\w*)\b/],
    ['', /\b(?:join\w* .{0,20}(?:wood|boards?)|wood (?:joinery|joints?)|(?:dovetail|mortise|tenon)\w*)\b/,
      'wood joinery|wood joints|mortise and tenon|mortise and tenon joint|dovetail joint|dovetail|woodworking joint|woodworking joints',
      /\b(?:joinery|wood(?:working)? joints?|mortise and tenon|dovetail)\b/],
    ['', /\b(?:dry toilets?|pit (?:privy|latrine)|(?:toilet|latrine) .{0,35}(?:no sewer|without (?:water|plumbing)|no running water))\b/,
      'dry toilet|pit latrine|composting toilet|sanitation without sewer'],
    ['', /\b(?:roof (?:pitch|slope|angle)|(?:pitch|slope|angle) .{0,12}roof)\b/,
      'roof pitch|roof slope|setting rafters|rise and run|roof framing', /\b(?:roof (?:pitch|slope)|pitch of (?:a |the )?roof)\b/],
    ['', /\b(?:draft\w* .{0,14}(?:door|window)|(?:seal|insulat)\w* .{0,25}(?:door|window)|weather ?stripp\w*)\b/,
      'weatherstripping|air sealing|draft proofing|door seal'],
    ['', /\b(?:ventilat\w*|air exchange|air circulation)\b.*\b(?:shelter|cabin|tent)\b|\b(?:shelter|cabin|tent)\b.*\b(?:ventilat\w*|air exchange|air circulation)\b/,
      'shelter ventilation|ventilation holes|natural ventilation|ventilation|air exchange|air circulation',
      /\b(?:shelter|cabin|tent|natural|building|passive|home|cross) ventilation\b|^ventilation$/],
    ['', /\b(?:reheat\w*|temperatures?|safe|stor\w*)\b.{0,28}\bleftovers?\b|\bleftovers?\b.{0,28}\b(?:reheat\w*|temperatures?|safe|stor\w*)\b/,
      'reheating leftovers|food safety|food storage|reheating|leftovers',
      /\b(?:leftovers|food safety|reheating)\b/],
    ['', /\b(?:primary sources?|firsthand (?:account|evidence|record))\b/,
      'primary source|primary sources|firsthand account|historical sources',
      /\b(?:primary sources?|firsthand accounts?|historical sources)\b/],
    ['', /^(?:(?:what is|define|explain) (?:an? |the )?)?acute angles?$/,
      'acute angle|acute angles|types of angles|angle',
      /\bacute angles?\b(?! (?:closure|glaucoma))|^(?:types of )?angles?$/],
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

  const wrappers = /\b(?:getting started(?: with)?|how (?:to|do (?:i|we|you)|can (?:i|we|you))|what (?:can|should) (?:i|we) do|read (?:the )?(?:novel|book)|explain(?:ed)? (?:it )?simply|in (?:plain|simple) (?:english|words|terms)|step by step)\b/g;
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
  const repairAction = /\b(?:fix(?:ing)?|patch(?:ing)?|repair(?:ing)?|replac(?:e|ing|ement))\b/g;
  const repairObject = text => terms(text.replace(repairAction, ' '));

  function prepareQuery(text, encodeQuery = () => null) {
    const original = normalize(text);
    if (new Set(words(original).filter(word => word.length > 1)).size > 32)
      throw Error('Use at most 32 different search words.');
    const audience = original.replace(audiences, '') !== original || /^getting started\b/.test(original);
    const cleaned = normalize(original.replace(wrappers, ' ').replace(audiences, ' '));
    const phrase = cleaned || original;
    const repair = /^(?:fix|patch|repair|replace) /.test(phrase) ? repairObject(phrase) : [];
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
    const vectorText = emergency ?
      focused.filter(rule => rule.domain).map(rule => rule.canonical).join(' ') :
      seed ? 'seed saving ' + phrase : language ? language + ' phrasebook ' + phrase :
      titlePatterns.length ? focused.find(rule => rule.titlePattern).canonical : phrase;
    const vector = query.length && encodeQuery(vectorText);
    return {original, phrase, query, primary, routing, focused, evidence, titlePatterns, repair, emergency, deliveryQuery,
      postpartum, pediatricHealth, language, seed, audience, vector, vectorText};
  }

  function hashTerm(word) {
    let value = 2166136261;
    for (let index = 0; index < word.length; index++) value = Math.imul(value ^ word.charCodeAt(index), 16777619);
    return value >>> 0;
  }

  function pairHash(left, right) {
    return Math.imul(Math.min(left, right) ^ 0x5bd1e995, Math.max(left, right) | 1) >>> 0;
  }

  function routeHits(bits, keys) {
    const mask = bits.length * 8 - 1;
    let hits = 0;
    for (const key of keys) {
      const first = key & mask, second = (key >>> 16) & mask;
      if ((bits.charCodeAt(first >>> 3) & (1 << (first & 7))) &&
          (bits.charCodeAt(second >>> 3) & (1 << (second & 7)))) hits++;
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
    const embed = text => {
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
      return vector;
    };
    return Object.assign(text => binaryQuery(embed(text)), {embed});
  }

  // BEGIN GENERATED EMERGENCY VECTORS
  const semanticRoutes = [
    ["downed-power-line","safety","8Q4NEQT9/PnyAfkN9QcRCgMCF/ACDwP4/gT8AQv87vv7/wD9/QP+/Pr2BiMA+f77//UICwEACAX6CfQF+P78BPf9DP/99vrz/Pv8AQz3DAjy9hAU/wP49QT9B/kFAv8A+Pv6C/8FAv0BARUQCfT4AQwLEfQCDQIJCf7w+vX4DvgEBAT8AP74+gj5Cfn3/f75BfwI+/4PBwILBPn1/vn/CQoABAYCAAH4APz9AAT7BwT8+gD9BQEFBQQJ/v8GCP8D+/sB/gEH/P/7Af76Dvv99wf//fb79vYE/wz+Bv0B/AYDCfwB+ff6APX19QQBAfr3/goJA/0E8/oE8wT8A/wED+8FBhrwD+7/9Pj8BwPu+wEIAgr5Bf8H9v8CEgUG/Pv6AQH4/BgD/xcUAwIZ/wH//gr4BAXqEgT/+f4AB/QADAT/EAoFC/X+/gLz+QgEAQ3+7/H/Dvf+/wX1Cvz4AQv7/vv9AwfyAwX2/QL6EgbxBAr6Bv4EDAMAAQX0/Qv8AgEN/ggA+/gIAAQTBgf5/AX/B/sCAfQCAQb8CQD8APz6+PoI/vsIAvj+CgcEAgD/9gH2Bvv/9AD0AAQGBAL9D/0AAv/4AwHv9gD+BAcFAQL4/wUBCAMGAPYEBAgDCwEEC/7+Df8BB/kB8f/89wEABgj9//8BAP/+B/0HCv3++wMD+f/xCA8KAP757ucH/wIG/wD2//0DAATy/gP98gD0A/37A//3/QEHAgMCEPQRAv//AfwJ+QoI/v8H+/r6+w73CPoE//0OAAXw5/0C+fv5DPwYBfcKFvoBCQP8/QH/CAwDAgr7Afz/BwH78QcHCwYHCfgBAAYL9AMA/gID7PwGAQUGC/z9BuoGAAb3D/oH/gH5AgD8/gH7CQUM/wP5B/Px//8IAAADBvf9BQQH8vkL/vj2//n1Bgb8Agn6/AcMAAL++wf8+Pr9BwYH/fwD+P0B/PIGBvz3AQD2AwsLGPoR+QII+PwO9wMF+/gNBQIHBgYDBvz//QAD+vr6/AD1AAcCDAv8"],
    ["scald","health","6/n6Dfbt6xHsAPb2BAv9AAEO9Qr5Awv6DgwK+vQA9vnxAhD+/vT2Aur6Cw0E/AoK+/jw//f++gQVCw4HFAD1EAUABAvz+QXzDgPuAQUI9Ab3AwYDAQH59wT5EfIE/fwABgD47fUA+w78/e4F+wHw/PL4BwX/AQr/CwMB/wYH+gIF//zy+wYC/vr8/v/+/gkB+gH7AAH1CQb+BQX8CAf39vwC/gEM9v/+/QPw/wAF/fr9//0E+Aj/BPoBAPsB+wQE/vz7Bff8/fcA+/sB9wACAAIJ/PP2AAYCAvgAAQUE+AL/+wUCAwD+BwL6+f/08P75/gUC/AMBAgQEA/gD/vsA//D29A76B/kK9Qz48PoGAPwGBvYJAf4J9Pv/BvgC6P/9BfwD8en+Bfv1A/gI6QITCwT2/Pv25AX2Av8LBg3/AfsI/v4F+Or7A/8SBwDxCwb8/fD3Aw8H/wEH+Qbu/QEAAQ8BAvf2EvIF/v0HBfz8+/3+CwIMAgUFAvv39AQAAAgEAgH3+f4A/gMHAQT//QgI9gcEAgYN/wMFAvD9/AkA9QYACwQGBf4MABD8+gD8+P/0BPf9B/b+AgL19hEAAP4KC//6//0HCP/7+wT/+QIJEAcQ+wz3Bv//Cv/79QgEBPwDBQABBP339v76A/0H/PYA/Qb8BgH+/f4E+voABAH5/v/l8/4M9ub3/P708Pb8CfMIBhnx+vkJBQj8CgD3BAMHEgkJ/Pb8B/jw9ukACggBDAAM/foZ7PT9+hAOCwUHAvsDAPr7Cvz2/gD9BfEFBwf0AgL5CQ0F/gX8BwYFAAQD+AQJ//L98vv0C/oKAgX1+f4O9gcGDQQAAfv++Qfx/vn/9gQG/vcA/fwG+QHwCAMFBwb6AwYK+Qz9+fsBAwD+Be74//0DCAQD/A/9AvcEAAIF+/4C/wH6B/8DBAIE/QoEAA/+/fsEAgP7//n++PkH/gEBBgL6AgIC9g4GAAAM/wH3+f7//vf9//oECAkC/v759gT+AQL4/QT/+gYD+f0ECAD7"],
    ["sunburn","health","BPEF8gP29QT69AEAEv//7/z2BfXyAAwG/v0TA/r2ChES/QH09vjy+fvr/wnz9AED9/P+Cvf+/fj+/wMD/wwFAP0Q8QME/vbv9/IECgv4AAYKCP8FEPf/BAD3Eff8BO34APvzCfQHAQfr9QIABgEUBPwLAAH4+/rsDgH/9xcC+/QE+gwI+f7//AL19Qr1+wAJ+wL6BQUCB/4EBQcHBgX+BP79+gkKA//2/f/9+gb5/wL+CwIFAwH+AwYF/PkE/v8HA/L/AP8EAgoMBf79Af38A/YB9//0AfT+9AQEAQgCBwUDAAAD+Pn7AwX6AA33BAQH9gUAAv77/vr/9Pf7+gT9/fXxCA8C6O/+APHs9wQJ9/MECwP07/cFBfoABAkJAA0VCAb78Qj2AvQF7/cE+vz0/A35Agn4Avb2EPv5/xIH+fcI9P8FAfUDCAb+AQ0E/PoBAPkCBQf7+wMFBf8EAQkJ+fzu9wT3BvYJ+gUB/RD/ExD/BwEMAgAC+/3w/fMBAAbvBAUI/v/8+P4E//n4/QP7A/r0/wkCAgP9/Av/DAj2+gz3AfwOCfwACvwG+AII+gj4APYD/PEA/QD7B/QBCgIA/v/4/gcB+/QL9wH7Cf3//PX+BgcH/f4CAggNBQUABwUMAQYC/vv9Agb5BQMFAwX5A/kBA/QS/PoE+v/6+gYP+wX78v4D+vP1+QjvAvP+AwHsCPcF/vEGBgPt9wj19vYHGQr8A/b9Bgz5++j8Fu0IBvb6/wwK6/30BA77Evz3DfcGAvj+AQgJBgf9+//9Buv0/AsO/gUNB/759wIDDPb9/fgC8/P6+wL8DPwBCAD6/woV9QkJBQH9+/n96v35Agb/BAEB//v8/vMH+P71BQIDAwn1AQIGAQr++/4K/QgCB/j7Bf73/wMG//36APn9/gYPBv8F//4G+vv8A/n8/AAE8/37AAkKAfj4AAny9A38//8EAPwEBgD++wb7BAUM/Pj8AAIJAgYA8/wP+gADAvYGAAX/AAAC//oAAgD6AP4DBAMA"],
    ["long-lie","health","9wQCBPz57wPs//8DBfUC+/v6BfsEAfX78vn9CPj+CAf79RXt/gASCwj7BgQOAgYC/PsOAv4SDvgI9QAO9v4GDAj8BwH/BfvuChMEBvLz+wUOB/D4+/rw+Af6Avf2AvgADP/2/AUEAe4B+wkFCvz39/4EBgAC4/n2/AQF+QT2B/8HBP4DC/8N8v/3Agn+CwP3CAD29v0EBAMM8wUG/wACAvgI/AoC/fYBC/f8/AwDBAr8+QT9/P72BP8LBgP09v4I/AcRCAT6BAcJCfn59fgKCQAA9w8E+f36/goCA/f/Bf4EAQUKAP0A/v37APsA9P0BDQH8Bvn/DPwC+QoF+P78A/D8BgAD9Qf0+f7+//r8Bv0H9vv0+f/0BPXxAQP/9wIK9wIJ+goFEQUD+wb5AvHoBgT99hH1Bgv9Dg79DQEC9QP99wL+B/3/+QMO+An/AQUE9AL/8e0EAvP8AwgCCQXzCwT45wv6AQnuCQ0Q+wzxAQUJ+AcFAwH5Cw/1+/oF8Aj7Af/+9wwE+wL9+gj2/P0HDP34BQT7/AP7BQEH/vr5/AL5/PcC/gH9/w72BP/+Avz7/PsHCf4EAPL8CgQCCgYMDPoKDwwCAAUC+wAEB/Tx///1+/4IB//++gQPAwbxAvQF/v3/BgYD+/f3BgH9B/YA//z//wIF8gHzAQP/BwgD9Pvx+AvxAPj1BwD27/UH+An89PgBCPv/AAv57wgG/Qj7A/j/AP4EBwX9CAAJ/gH89Qb8/QYN9wn69PwB/hEFAAIIBQMD/wL+//oJBgcQ+/cHBv4D8fP9AfkC/P8H+QYG7P0GAwb3+AsK9vgB/wwJBgMEBAcH/wHqAQIM/fb2DQIB+gMB+AMJEAP6//UI/fwME/wG/vf5AwIBDQX99QMJAv4BAA/yFAAABgMF8P0K+fsBBg0ACQAH/f35/f8FCv4F/Qj4+gr3///8ChUMCPn2/woO9QYACvoB/AH4D/cC+f0C8gX4/xP19/z5C/v2AQn8CwQPCAEJAAj2AAn3/QUABPz3"],
    ["fishhook","health","9e8EFvr39AcCAg8A+wr8/QEBB/cG+gMMDvcCCAT17wj9AAMB8/wJ+Pje9wz/CgT/7QcF//4EDvkF//n99fHp+vrzA/f97PgT+QQA+/j+DvEG8hcRBQEGDAIBCwf9AP0DBPr7AQoOBgH5AQP5+QUNCQcJEwYI/wAEAwATAf0B/v8SDPj9Bf8DBwn8BAEMCf/5/PwFE/0BB/gDB/n///rz/g4GAAT//QMFBv8IBgD+BwH89Af4/wL9/f3+BQAEBgj/AfX+CQYI/f77/v8ECPv+APgK/gEG+wb+/gAD+Pj6/AH7Af0C9gYJBvsBAQb4/fwA/wQECgb9/gAD8QIIAwH5BPMB6xH5BQYB5wMIBfAZ6QD8APoKCPMN9PIGCgn3+PkS+v/95Pf6Cfn0+QD67fb0CP79AgD5+Pz+EQn5CvPw+AP7+Pf09ggIA/0LCQr9BwL4+wIKAAD9AwH5CwQA/gb6Af0TBfMF8P/2AP70/e4AAgoA+gMBCQIDAugI/wD39O/2CQf+/P0C+vP89wv/BP0FAwYAAPn9/gn/Bwj8BQQCBP8B/wIGCPD+Cv3+CPgECQEE+AT6DQMIAAL6/gH9+vz+//77Afn+A/v/AgD9Bfr5+gX8AQQG/gH9/v8DA/4CAgIGA/b6BQAC/AH/CfwB/v75CgUIDvcIBf7yAQj9Awj+AQXx9/8V9v36/vr8E/rzEOz3AgQB+gf6/wX+/goKCuz3Cgf7/PTv/Azx9un5CfYA/wLuBgL09wQD9AoE/wf18PH9/vYD9QH0/ggE/gv8/vwQ8//0EQ32AQkMAQH9AQAF/wP59/3/BAH6AgH9AwH1AwoJ+v8YAgwD/gL8+hD8BAD2+hUQAv0J/gEGBQQFAAoE9/z59wYI+wEE//4H/QYGBPP6DgAEA/34BQ8B9gUAAQUK9Pr6Avn9A/f4//wE/wALCQIC7/r/Af39/vgC+f4G+vv9+w7+CwYBAAL7BAnz/AD8AAUC+AX2AQX/9v8CBAP49wf9AwgDDAb8BQHzAQgKAv8G"],
    ["embedded-object","health","9Qr5DfX9+/D1BAr9//z1AQUPBvsEEQn3Av8BCAz0+g0OAPn7CQoD/gXv//Pz/vj89QEF/A72//UNDAcJ//n+BP75+ez19wD8Dv/2AO/++w8G/wP9DvUJDwAC+fP+/fQJAgABFP0JEPoBCQj7+f77EwkP/wT+/vTp/wgABBH8AP8K8/oE+wAAAwD5/A4KBgUCDPkE/wAI8AYEBAf8CA4D+wEN/AAC9woI8/v+/vwJAv71Afbz/v8CAvr8CPsLAQAIAP0A9vP++/H/DfH8CP0LAf0HA/j++QUN/AABAAf/BvoGCPwD/v0CBP8A/QL8+vYF+ggD/gv6+Ab8AgT9BwAJ/fQA/w78B/3vEvUI/BLzDQP8BQT9Cfr6BQkC+Pz9AQn8+vn+BQDyDQHzAvoUBAH9EP8DBgUH/v0TC/r8/Prw9Ab29uz9//r3+wD9/Q35/fgG//j6/fb9+RH37QXv/Az+7QQR9QHyAAb7AAoBB/j37fUCBQwPBgb+9Qr9AQn6A/L2/PX2AfsK9v76/fYB/A38AgsE+wAA+PULAgAK+Qr/+wID/PYLA/v59AkG/AL9B/j9/wj7Awj9+QQK+gYCAv/7BgcFAv0K+wP3DwQC/Pv//QX8AQPzA/v1/AIC/PP9Af8ACQb+DgICBAf8/f3/+fDy+fsLBgEL/wIBBwEG8Qj+AgHmB/gRAfkC7PH1Af3++wH5CAUHBfgGBgb99/z9Ce8I/QIBAekH+gYC8fYCCO4G8wT5A/73CQb/DBL/9wT0/f8CDvn9/gH5/P0I//oC/On7Ffz1CAICBQMA/f8F+AH8Bvv7A/sCBPwA9gECBgT+A/YGBQMGAfT+///yAAfuA/YI9gQEAfr8/vz/8Pf+DAQK+AYC/AYG+wP0AQf8+/0GAPsDBf36BQf7Awf+BAUDAQED/QMJ+vf8BPYI9vcGAgEI8wj4+fD1+P4B+AQF6fP1+foBBAQCAgAICgj/AAb+CQXyB/j39BQD/QEI9v/9AgL87Q38Cgr8BQf8C/j5CPwTBQv+"],
    ["jellyfish-sting","health","9/0BAgH3+/z++vQH/wH5+wECFv4I+wcFAwT0CfT2/RgC8AriBPr8EPv2/+z6ABj3B/YJCPgE/vkEAfgEEQf1AQAE+QYO//oO9vn7/gwF+gAAAwEBGA/9AgEH+g8G/vb5/Pj2AwIS+wQBBRDr/fz9CQgQ+QcE/fMCAQH9APMCAwcHBwb7A/wAAPMJ/w4EBgMB+gH6Afr6AQIECAMFCvj78/z/+wYD/gYGBgn+B/kGCwHwBQL7+vwA+P8CAv0B8/4G+QT9AP31Bwj9/gwR+/j+/BH+/wP9+fr7Bf4GB/0CCfYBBf0D7wL8AwII9A75//0B9/0GAgT5Cvn4Cfn79gb9A+/t8gL18/ft/+7vC/8B+QID/Q0KB/4E/Pn4BQnzBgkJEQcD9fv4/wPs9Pj+/P4FC/btB/f/AvMFBRD6ARP59wIGBw0GAvry+BD0Bv76+vgA+PUNAQ4BAAsDDAj5AgwECP0G//8AAfwHAfP/8P4AABH/Aff/9vTuCvsC9v4C/vUBAQX8AAMJDP3++vkEB/3++wb3/Pj/AfgC9wgFBwr++vz9+wUI//QKEPn/BQcECf/5/QID9/b9Af35+wkGDPz7A/z0Df8N//UG/wsCBvr2/AH/9gv89gYAB/0K/QEBBgH4BgT6/wP8BQv7+wYM9QD6/vUN+v0G+/8HCf4G//oOBP7y8/QF9fIA+QDzEA37D/nzAQQZBAoACfoL/QMI8+72/xoGCgT47RL88Oj59/vwDAUB+gAB9fr//gQG+gIQ7/QC9wEK+wH58ef98gMJAfT29AL++gkVBv/++/wD9vYGDQIEDP37/w39+AX1APkCDPP6BwX9A/779/r8BAL++AP2Ag8G//0EBvwGAPkGAwsVCQcE//r9Bgb5/QEK+wEJBAPw/PYFAgL7/QL/AwT9A/8A/PsECPoDAf8IB/ME/gH5/QcF+AQE/f4A/gQT+wH8/gYDAAn/AAIF/P7+B/z9+gX//gEH/QUL+/oC/v8DCf39/PsACAEAAwEACAb++f8CAAgE"],
    ["tourniquet","health","+vr4Awf0++/3AQgFAhgC8QACBfzs/A4ICfvpBwv09ev98fgKCO4D7wD/8vgF7BIM7RAM9wUB9/v5Bgv0+gb/+gL9//4JB+n68AEE9gUDEP8B9fcEBgMEDgAJ8fQE//r6BPoB/w///PIGCgj7A/37BAUDDP//7Qr5CAb9Bf/z9fME+QQIAAP5AQkGAAAKEgH+/QYEBvj8Af0F+wn+CgXx+v4G/vsM9v8C/wD+DPj7AQPwBAT+BAQGAv8GBAQH/v4C/gYH/gME/wgBBf74+fr8AQMKAgoEBwAA9PUI/vwDAv3/BPIC/P79BAb5/Pz9A//9A/sD+wEGA/8C/AD/BAQAAAIA/f8BBvj++AH+BAYRA+8B/AD7+Q0HAwkG7A4G9/X7APr2/PnyCvUEBuwBDP7+/uUS/gMB8fb67wEE6/799gMHA/UFBv7yAPwFFf0HDQYKCPj1AwENCAAJBfH5+f76/QT2Df0Q/v38Agf1+wv//fsHBgkCBfkE/AsI+wP8/PL0BfoH+gQFAwcPCPz9/woCAwj/Bgvz+QcAAgEA+QMF7ff++QEBBPr/+AkFAQwD+wYF9v8G+gH6B/oEBQELB/b//gUE/fwEDf4G+wH88/0BBPkEBPML/vv8B/jpCAYEBPr29wb7/QED+wQL+//++gjvBP36CfwC+xQHAv3+/QEL9/rzBwENBOL29vAD/gEHAAQCBv8TAOv/DQoB8fQMAvr79fr7+vcO//EC/vv6+gXzEQwBBAvzDPgH+AQPEv8BAv7wAvsI8woF/QD5De/3AgEADfkGBAYPCgEFBAL+CQQH+QIC+fMEBf/69wn8AwMBBQILAAT4B/71/QECDPv2+/QK9vz/CwcP//0A//QQBQELBQAH/wAL8gID+/8DDPz/CPcG8wIG/QP1+wwBAhIP+/j9Cfb5/fL7/wwBAQj3AQL+BwT+Bv3/BgX7AQEE+wH3+QoBDRAMBv0CBfv2+AEABAL8/wQLAvkK/AUD/AAC+fwIAgEABvcFAgj2+vn++e8BAQIC"],
    ["root-vegetable-storage","safety","C/YECPkE9g4GCPTqCfr3F/gE/PXxCfoG7fb1+v8EBwYLA/j9AQf+Bv8I+uz4AvwJ/vPvEAr59/oHAwAQ9w/t/vXxBP/4/wf2AP33AQT2A/72Dvr79Qv/Avfw/AUG/fYNAQUIBgoC+BH79wAICv0G/wH++woIAfUJCf/0BQL5CQACA/YE/RAB+AAK+/QABP4H+gUF+vcP/v0CBgUC/fz8BAL+9/gH9fP+/ff88gb5/AAB9vz7BwYDBQwKCPMCBvv4BwP0BPwBBvj37AsECf/+9AD9+AD+/vb5BwEG/wT8/wX9CAP9APkJAfcACfj89f0DBAgH9wMHBwEAAwMO9wD5BAfqDwHgDPr/AgcL+AoI+hPz/vvjAv0LAQUAAQgT6/UA/f8F7/sF/woGBgoJ9Pb+E/z/Bff67g/0Aw8G/AEHAQv09ATq+gIHBP7+9gAH/QsJ+Ar0//z2BQEK9RL9Bv75DAkE/PkE/fgECfQDDAj6BQUA/f4S/voHAf/9/gcGBfYNBAMB/w0B/fX+DPUQ/fz2CPX5CP8AAgP8+AED//b7+gAGA/z8BQH4Af///gEL9vr9Afn6DAIAAQQJAgL2/AX6+P8D/P7+/Ar8+QAD/gEMA/n69gD9+/r7BwL2BP0ABwEEAfoB/P8A/wDzAf38/QAD9gH+A/b5BgD9+PQDAwD9/QkF/gYF/QsAAgcAB+0A7vYH8QH/8voA/wv4DPv6ABEC8///8BAL////DA4F/f8E/v8LCfkNBfoC8gAJCQn0De4B+vYN9/b6APf3A//+CwAI/u0A/QvsCgEGCf30CPwI+RL+/P0ID/f/BvbtBQ7/BgQOBQML/v4K/gQAAPsFBvj1/AL7+voFBwD6/f759/cGCQL7BwL7/wsG9//8/P4I//4DAQD7AAjv+gkD/QD8BvgBDAHz/vj6/AcGBxAH/P8E/vL39fL+/gIK9vT0A/cH9/n9BgL1BAXw7gMUBggDAAf9/P0A+QMF9gL8APoR+fr3A/v7CAv9/wMFBAD4BAUE+/wG"],
    ["grain-storage","safety","CfoPDufv9wIDCP70Cv3/B/z1+PkICv35AQj/7Qj/+AYT/wX++wT+/fcQBgX8/vH+9AILCvcKBvwA9f/3BAcCD/74/ejy/PsECPvn+fr3D/r9AAkH+/L/+wnyBfzt/PwR/AYA9Abz/vwC+vf6AwkKBwPz+wn9+voBCAP2DQoEDvsO/vsMAgz4/vIBAgIAA/4E/AIFBv0X9/3y/gb6+gYIBPgK+f8D+PkDCQH8+vnxCQUE8/0BCQQEEwn9BPQCAAACCgH8CgD6BPn7AgP6BAf2+vYCAfz//PP9Cf0A//0A/gb3B/7+BvkK9vcFBQL9+/v/BP4G+PoDA/sB/P0AAv38A/kBCRHz7/D6/gDu+gn9/R34+PsDAfjq9QL/AfMB+vYOEAYB/v73/vrtEgXz+AHv9v8G/wf7CfcG/gH3//wDBwcF/+zlAPQDAv8L8vn9/QENCQD//Qb9/PgF8/789fruAe//9gAF//P8/P/3Awn6CRP4/AL2BwH6/wYJ/AkEBv0EEfP///UNCPz1Av0B+AH39gP/+/oAC/L5//gB9AEEAPz+AvoGAfQCAQv/9/0C8QsIAfP8AAL7/voJDAjvAf77CQwG+v4E9gEAAgcP/PcJ9f8DA/r4+gIDBfn5AgH8/QD7+f38AQP/Avj4CAQEBvn8AwAEA/8F/P/8Af4A/gADAwX/+PcR+Pv5AAUT+/QG8vYL7/v/Bg8D6fMIBvn2Ef3nEAv8/fnuA/7+BRQI/vYA9QEEA/wHCfz7BvH/BgD6AxEKCvPk8gzy/hQNBPP6+vUDAv4AAPX0+wb0BfAB/PwG7Qj5AAIC+Pjz/vb5+fz8//4BBfT8/wb//fj+APX8/Aj8+wX0CP75FPz58vgC9fgI+voE/AMA/AX4+fnx//32DPb89vYABgP8+/0IAQAG+/0ICPzu/Pz6+/39CAQD+/f5+/wBAQACBP8EAAH6Bfr6Dv4C/fv8+/wF/wX/+fz8/P7+/f0AAfj5//0D/wP9AAUABPoAAvb5BgP8//j+BP8J/QAA"],
    ["newborn-resuscitation","health","8//2Av/5+RH96uQCA/72/gIN9vwC/f8DAPQHBPAM9fb6CAsJDAD+EQAFAwkFCPcL+AL7AvgC/vrz+Ar0+gP+BAUJB/8F+Pf8C/7tDAD7/fsBAvz8AgAO9+0M/gv8/P3+D/3z+gv1Bwr79fkMBATx+/cHAPgCFAMIBgP3CP4KBPn2+fP8AAn9CwkDAQEMBwEA/ff5APr0/gn6//0B+QgIAgsDEfkE/wn6+fT3AwH/Bfz/AwUEARMBAv/1+wbzAfkD9vUIAQEDCQH6/gcQB/oIAwAM//4AAP8B8vny/fYB//oA/wfyCP0FAP8G/gL+DAH7Bf39FwoOAPsEAgIC9Pj+A/H28wX/7A8F+/ztBvr5CPkCDPz3B/r+Af7w/QrzDO/89AwHAw789hP57wPxA/b/DvIDCgL+/u4C/Ar56/72/f0J/Ab7C/XvBhAE9/0N//X5Bf4G9/7yBwL1Bvj0+fnx/AP87gQPAgMIAvX7BwH/+vsDDvz/Bgj5BfgF8P74A/0A/wz39QP6APwDCwP7CwL1B/368/cA/f/59QcEBgj8AwL5/wQHAAYDA/z0/fz+CwP5DAf+/QQH+A8KAfwEBwYACvzxBfkD+QQG9gcGDQUEAwMFCAX3/AUF/fb2/P7+AgL9APsGBQMICfv9//UDAwT8+AUDBg0BCvoDAwv/Avn4//7tBvgF7f7wEfro7fn//PD4/w78AQD0+wr69wUJ+gj08QsAAAYC9wAMAwb38wgG+AnzAgH1/gP+9/HzDOr9B/cJCAkN+f0E/gwA/vMHAQP0+fsG7wIB/wT0BwAACPUDAAAGBf/6GPf7+/v0/wgK+PX4+QLvAPkPAPYE/vgA/P8FAvb/++wEDgED/wb7Bg0I8/0A+AQB/fcCB/r+AgT5BAX3/AUR/QUEA/kD8voKBQkA+Pn9AwwCBwIFAAf9A/34+fv3AP3/9QEE9/0ABgUGAAkMCAP2+v35CAMA8wIG+A7++vwE+wAE/fz+AgP3+wMGBAQACf8OAgYC+/T9/QEF/AgI"],
    ["newborn-warmth","health","9v33CPf5AQH++OgDBgL++QQL9/n7BAEG//MP/gIA/gMIBg8IAP30EPYIAAIEAvEF9vL39Qb0Bf/6+/z9/wb6AAYGD/MD8fnxCgEBBgT7AAH6AQL59fwF/vYE+fsA/Pb5DwMB9hHzBQPw8gkKEv36BQQJB/kGCQH4Cvz9CfsFD/IBAP77/QwEBgUFA/oPC/b/+/X2BAUCBQbv/wgFCQXzDgv8B/YHAgUE9/P2CwT+APr/+/0C/AwCAwb//wsFCPMB+PQLC/sDAwwGAwUSDP4CCAP7AQgEAgX///vuAfYD9vT7Af31BvT9BQH9/fv4GQIA9wb/Bwn6Bvr9/Ab9/vP8+//2BBb79fUJAu779QILBwX2CfgC+wP59vLh8v/2APwIDg4N/wYH9gjxBv/99QD1/fXx/Av6Av779vz+/v4F+vkC9OrzEfP+BAcD7gQKBf0CAP0CDQf9CAAF9/0C/fT5Af32+/kHAA/+//kAAQf2Awz9/vX9/QcCAg38/AMB9/8HBwz27v4KBAf/+gT7AwX/9f78Afr6EAL8/O8EAv0N/v0FD/79BvwCAvvv+v4L+g0KCv38/wQK9wgICwDwBgP2CgL5+wL5BgQB7/sLDQEP/gcMA/wK+v0BBQH8+fz8CPr9///+BQT5AAH6AgP/+gD+/wcBAvT+AwT+/P4LCAH+9A7r+PYG+P0F/vv/8fz0Cfzw+Q3xAwINCgX88wcE9gYC+Q0TFfj9/voL7v8BBvwA8g7x7/j6//8FBAMPBQf8BPz/9v0P/gLx+O0DAfoNBOsA9v8L+/P6Agb4+Pr6+gn2+PUDCPr7BP7+CPjzDQAQ/wH/AP/7BQkNAvIJ/fwP+wb/BfwCAPT9DgwB+wUB/RP/+gT6AQIJAAcJBu/+BQgFCe4AFPwK/AEJBwAG+PcK/v//8QQF7wQJBwIDBQMDBwYJ+Aj+9wX9BAcECQb//AEFAAH5C/sN+gEHBgUH+gAC/AL5+vr+AQL9/v4ABPz6//8IAgT6BQAADwD/AwH6AfX6+fr/"],
    ["newborn-jaundice","health","+uT2/fPyB/0K+fn+BvkQ8wUGAQD6AwP+/esDCPsL+QwC//79BfUCBPTuAhP8+Pr87gH7AvX0/PsAAw/5/gICBwcNA/r9AQMBC/0I7gL0AfQJ+wQAAgQX9/oJ+gj3/vHv//wC9PkC7gDv+Pv2/voKBv0KBQcQBvr48Qbw8wID+AX/CfzxBwUCBQkK/QsGAP8TAwH8DvMCBP34AgH++QD2Cwz8CgH8CPf/+gD6AAMDAfkDBggE+wYHAAL9BgUHBPYL+AMLAv8JCg8G/v8F//0FA/wEBP3/Cf0G+wj8BQX+AwD8AQUABQkFDQIB/gMAEfb+AgMFCQIE//b++PsD9vXyBPX4+v0F/AYI/fj0+gMCCfL2Bf0H/PMHBfjuCAf8DfsNAwn4/wUG+gH69AMF/Pn7B/QCAwrwAALyAPwVAgcOBAoGBwP8+QMHBQP5BgkI7v0A/vb4+v8BEPUBCPkP+Qvt9xP8/+/2APsK9vP4Dv78BvwAAxL9+f32A/T58O8EBQH8CwP5/gIKA/wCCAIG/fsKCAb7+f4FBgP8/vz7BgELAgIHEf4BChT/APr69AMK+g31Av8FBQAMAf39AQAI9gPy//P5Bfr5Av0QDv8B/fcLCQgABPv/9g3+B/gJ9QP4+QLz/vP//gL+AgX/9fQH+AMB+w8D/wX6Bvz+//bzA/35BQD/6vEA7vQFCQr7+vsLChH2+BECAfzp9vUL8AEK9QT5+f36BgkPAf4S+/ABC/z9+/Tg/wz99Pn+AwT5D+8GDgcFBQPu+AID+v8D+Qr1DPoE+Qr9BAgD9gn5BQUBBfcF9vgP9Pr8APn8+vr5/QT19P0I/gILBQ4C8wH4Bvrz+vr3/vwCA+wCBwECCBABDv/6AwH+BPkCBAAP/fj1Bgb8+gL+BQEDAQkI/gD6//r/CwIF9gT/Bv36AAQCBgUA/QYB/AoI+woF+QkDDvcACAD5EQYJBQIC/f4I/gn9BwID+AAD+f77CPsABwcF+fUBAv4C+/sIAQMG+/wB/P/++gL79gME"],
    ["newborn-seizure","health","7fj8FvL0Df376AAA7xIM6PwD8P0CBPH8AfL9CuT+B/cI+hb8+f4OCP/5CvwM/fUB8fgC/PkG8gL4AA8EB/UK8g4J+fsBBv4BAATw/P0FBPUC/QT5+QQMAPMD/QgIC/f59v708AT/9/4C+gcO+/H0/QUE/QAJC/X/AQL28voCAAYB+v/xAgEFCAsCBgMD/fkB8v73AgEA/vsE+/3/+wL9/vsJBwEA/PgKA/f6BgoA/vUOCP4A/gYBB/v1Av/3/vYC+/sNAfr9BwH+/AIKAwMJBPz5/QD1AwEG//sMAP4GAPv8BwcL/gb+C/j8/wf/AfoCBgH8/AIJ9gD6/wICAPv0/O30+Qz69AYSBfj5CP0C+AD8Bvn++vPz9vDsDBv1A/sBBvkO8gL1Bwz5AQj5A/f8CAEEAQnrBf/+AfYBEQv7AvkSAwTtAwH//wEJ+AgR/hD7AvgD8wL+A/r+BgUQDQDx+v0FBPz8AvcIEvcECgf7/AD3AAv4CAb0DP39/fn+A/75Cf399gkFDAD6CQYDAg79//73Aff3Afz8//sCBQj7+/oEBQgCCQUGBPzx/wj8Ag35APsDAQQEBAPzAwUD+/4JEQD+D/4D/wQFAf8IAQf9A/X5BP8K+wcED/sHDvr9/gH9AwMEAwX5+f8DAgL+A/8HAgb2+AcHEwD1+AD6A/P09ff0A/gJ9QP9CgTy+Az9/PgDB/75/vT59/X/7vwM5gH47gcNBAn78PoOAAAWCPj7+Pz4BvIF+Pz8C/j0CgH3BfX8//j9/gL19wUDEPgC+AMC9fz3B/j/ARD+BQj4+ff4/fsADP3wCf79/Aj3/QEB6f4E8AYC/QwE7v4G/PwQAf/3/Pb9/PUA9wgECQkA+Qb8BgUF/wH6Bgb6+QD48vsDDQUC/Ab/+gAFAgAAAfb+BPoEBfsB/QkKBvsI+ggNA/wL9Rv5AgIB//wBAgMD/fsJBQEHD/8N+fT8DQsAAwT8+gb6Av0IAAwG//wMAf8B+QD/BAD/9gEFAQD/8AD5Afzt9AEE"],
    ["preeclampsia","health","/vLvBPzz/e76//EL+g8G7wTwCv/v/w0HAvf//AMC8foG+fT9/fv6A/r2Awfy9PQC8g7+6An/DPoN6goBC/0QAwkPB/UFBQD77/z4AgEF8+oA//b18Qb9AvgA8Qf7DQID/vT0Cf797gL69wAE8vwBDPgGBQEICQv++f74/QgGAP369A35BwgFCQsF/v3+Cfb8CQUB////9gMGCAIF9wH8+AgDCAIBCgf/Agv9CAT99/wCBQr7+w3//wH3+gIDAgEDBP0B/Qf6B/n/BwX8Dfr8Av/4APsA+Pn1BwD7//wCCP4CAvwT+AUECQEAAwIBCP8NBQgAAgj9AvsBBwH/8vn3CObz7gP08f8S+fb1CvwEAwL9/goB8fkGD/vvDQcP/vz9B/j9CgXz+fT5//sH9/MHCPYR9/4J+gH9CQb+BQbzEAn4Bw0HCvn++PUC9AL3/O788vn7/wAI/On4Avr29BcC8AL7+wz7/fAUA/z2CQn7Cwz7Awj/BwgBAPX/Av/++v79BQj3B/4QAxD4CPT8AgL+A/r8+xH4Af/5AgUAAQkJAPwAC/n8BAIABwYBBQcCCP3/+v0B+QD+AwUA/gsA+wsL/gD8Afn/Bv79CAT6/fz+9f0BCg4GDwAC/wMK/v0ECAcA+w4CB/n8Bf79+gn/+f7++wUA//kEDAP7BfkBAQUD/wX1+/IA+PID8wb/7v/tCP8ICPQH9vH7CAcD8gYC/vwB8gkI+xb7++j6+Pv/CfXr/esOBwH6DgQG/wEBCAb+AP4DCQ4DBPz9Awr7/fQMCgfz7fjzAu/+9wT7/vP/Av8E/AL/+fzu+f7/EgAJAwz9DAMB+v0O+AsADwzx/vgFEgYH+f74DAr6Cv3/BQf4+wYJAP4AAf/4APX2AP4DBf38CPn6BQYTAPsDAAgHBvbyCgP8CgT/AQYAC/sCAvnx+wAD/gEAD/oEBQICAwIDAfsBAwED9wb89QEA//kEB/0CAQQD9wgABfz/+gYB/wr+/gwPAgfz+gAC+v/5AAT9Cw0D+/kC"],
    ["ectopic-pregnancy","health","/Pz79wrwBfXqA/j9+gcE5wIRCvzb9wH4DQQMCxMCDQAC9QQBEwQD/wTvAQ7/8gIGCPwA+w798PQKB/sHAAMOAAD1C+wCBgf++wMABwD98/71/vwBAfoDBAT7APICEwgN9/X6BPsB+/n2/gkF9fcOCfUKDRL4BAUD+wIC+foCBv/0BQMCC/v6+wYC+wb+C/n9Av31AgQG+P0D/wEGCvz9A/r8BwAB9e4CA/sGBPwBAP8D/gEC+wb8B/wFBg3+/Qr7BvIL+APx+vr5//kCAPYC9PgJBQwC+wf7AvkBAwUKBgkABgX+BPwH/QL9CfkE/f38A/oB/wMG+AL//wkIBQX+//kH6/0C5vf/6Pz3EBIDCvQJBvn76fQNDAf5CwL3+fL68v0BCgUC7gP58/4CBPD2A/QO+/ry+AD/DwgIAgIGDwIFBAzxBwH/8gf1BwP7Bvz++fjwAQr5/gYMAgHy/QsI+QID8vr4BAP9/fgABfwA/Ab47wgB+gcM+v4E//4B+P378vcIAQAFBvQLBAj3AgP8BgAB8wj8AwkDBwr8BP38CQkF/QcAD/3+BwgDBgMC/P/8DAkPAfn4CgEBC/4NAAoG9AX9A/sHAwMFBwoB//wE/f8AAAAIAf0E9wMB/gIGDQEHCwEGBfr/CgL5BP7/Av388QD7+f4J//0E/e///vT/9gX38fQC9/j++OoA9QMF9fD9/wD3A/Lp/v0JAQYL/gkI9wP+9wT4/OcQB/P9BQAA+PsJBwD38gDy+QgA+PsKCgAICQ4F8AT0/AcSBv749v3x6fsB9wUN+/kP7//z//YJDQgJ/P0GCfP2AvL6CgT3/PP+9f8VEfsJ/wQFARAH+QIACfX8AwH3Bvr7Cf//CwcIBPr4A/wI9wn8BAEICwkBBQYKAQgNAwX6+/z++gIKBQYAAQ8DCvX+CQD/AQb9CvkIAwYK/Aj4/wEAAwUEBAMICAD99/QHBP/1CgME+/wD/QMDAvz/BP3+AA4B//kCAvsCAP/59wIBAgQCAf8BCwX8/wD9"],
    ["bleeding-during-pregnancy","health","7/Dq+/jy/AcJ+PAKBff0/AAK8vj18gcO/PYLBwQC6fj9A/8I+/b0Evvv/gb59fII+P4B6QAF9/r5/f8EBgn5BwsCAvwM+v8E/Qrw/P30//X29fv3/vcLAPsJ7ATzB/kB/gD88QHxAwP5+gAL/PnzA/4AAhgJCwMB/v/3BwL/+fb79vr7+w8CBAkL+/gFC/4BAPwBB/0E+hMBCf4FBAUC+wb7DAMFCvoGBvkACfsHBf4B/gEFBgv6Av8I+gj8BPwF+AMG7wACBQkJ/wQCCAr8CgL2/wYB/gr8AP7+DPcGAvYP/wMF/f0D/P4G+gD7BPz4Bvr3AAECAv4ECAb68vf9AvLr8f3u8PsJAvD8CQT49fUDCv3z9fcJCAHxAfoGB/H7B+0IBgL+8hcA/QQF9vQB+vz6/v38/QD09wAGDAD58//3Fff1C/4LA/gG9fr3AP72+fj4A/j+/gD+CvcF9Ab4/vYLAfAA/wz1+/gJAvUB9/j5/vISEwb+EAAG9Q4FCPUA9voH/P0DBv4HBgP2AwwJ/wD//gcE9vcRBAYACv/7B/0D7gb9BwX0/QXz/An8AQUA+fsA+/oL+f76CPP7/QL9Avz9BfgG+QUBBfoI/gkB9wf8/f0L/PwF/Af9AQkAAwX4CAX9/QEHBgD0A/oF9wX///7z/gj7AAP3DAgE/fr6Av4E+/gAA/Ds+PwB9fsK/gL3DQQDBuz3AOkG6Qn6Cgfr7Aj/9wUBCf0K+vHzAQHuABYJAQXyDAby9gENCP8FCvH6DQgH9AMDB/f6Bfj98Aj88PX1+wUG9QL8/P76A/sDBf8G/QT8Cv4EAPz+Bgz2/A8FBvz2/fv2BAP9BPoGAvwD/fgCDwgA+A34BgX/+QIN/wIJ/PT98f3/D/8GCgIC/Ab5+P0HBfr9+AACAQgHAwACAP0CEP71CA0CAhHz/wr+BfoDAAXyAfgJBvz+/AIE+f38DPz8CvsEB/EF+gYC/gkEA/4FAwn++wH8+QYDAAUFCPsL9wUI/AkB+gj/Cgf9+P4B"],
    ["placenta-praevia","health","+vX5/Qf3+/f69/n/CAQD+AUA9/3q8BH7B/wICQr59/ID+fgJ9QLh/AvtAwP26v0H9/oD9QUAA/gF+AcJ/QgJDQkG8+4MAvv6/voC/gQGBPf1/PsFDO77DvsE+/kCBvkHA/71Bf39++3t/gMD8wMLFfYHBhD2CwP4/AkADAj39/D3/wwK/v//+wX8AwH9+P7//AT9BwICAQoBAg4IBwMJAQL8BQEN/fECCfUFCAMBAgMJCAkGCAf7BAEI9gcBDAMFCfwA8QwCAwoEA/wABv//B/v99gv/+Ar0+/3//wgG+wQIAv0AAfsC+//++QP/BAMAAv/+APQDAfoB/gIA8gb4CAUG8QMB9/fs/v/m+gf9AP0JBPMF8fgQA/3rBQkFAfj1+/j7CgoJ/w74AAD5Aev1BgMAA/H9B/3sDgEF/gEF9gMG/wj0DAb/9QP+Af8AA/nz/APx/vz0+QT6/e787wj8CQny+O4I/A7v9v0HBPn1/wr7AQkB9wEGBPcG+ggJ+AUB7PkQCQj2BvgKBhH1CAD99gL/+vf0/gYAAwsHBAYNAQ0H9wUB9vwABAj1BAD5/gMC+f0E+/oNBgb6DfwPCwUG8/gAAvIGAf8CAf4DBv4FAg8C//4IAAQG9gX+BvgIBwD3+AYAAQEEBwEE/AMF+gAE/gH+/wQEAPf9BgD+//4I/QENBPQD+vPt9PX68v4K+vn+Bwz5C+rzCPr66P4B/gjn9Pj3AQID//YR/vQC//fj/w/6AgvxBwj66f/9C/YIAv0AEwUH+QwAB/oFCP4DAAH86fkA7wn9+P/6/AT5/ewB+gUH9f/6Bf3/9vb49Af6+gQBBPz+/ff6/fn//v8LB/8E/vr+DP8E+//7CgsB+AEQA/gD/v74+vv9DvwIBgb2DQQBAAELCAP9/QMK8wr//P0HA/oIAvz8DAkGBQ/9CAgC//f8/QL1AvsDB/8DAgn/AwINAv75Av/9D/0J9f8DAgT6/v/+BgUHAAn++gQCAP8GAPX+BP0DAwj89gcA/gIC/gT/"],
    ["placental-abruption","health","6PT0Cfjm+fbs/+/+Bfn79gUC/gbk+wMDBfkPBgn++vsB/PIG//joBwTxAAgA9vQOBgIE7wcD8PwI/P4ADgEEBA37CfIC8/0KDRH0//oB9fju+f4HBPP8CPoD+fT0CAIDBgLsDAH5BQDu/wgB/AIBC/4MDgT+AAH9AAwE/QEEAPr6/wMPBgT/AQMJAAgJBfsB/AT8CAAJ+wIDCAsEDgcBD/v+CQUJ/QEDAfcLDvoD/QII+Ab2/AME/gIF9gYEAwMA//kL9QP4/QT+DAIDBQQD+vYCCAz4Agb7AAD8AwQA/vgDCgT9BAIJA/n79wf/BgX3/vwDAf7++vkE/Av5/AcDBfXu8gj96PD8+P3qAAT98wb9AvUF+PEGB/r2CQT/B+/1Af/5CPrz9hoC8wIE9vb3CgYCA/r3/PryAPb8/goK+AsFBwb0A/P8AgQQ+P75+vTu+/vzCwLy/AfvB/QE6wQDCQLx/fsK//3/+AD8/gb+/gb8BAkO/vQG+wn/AA36+AYD9/oJAAIF+wMDBwYCBQsC8gH+A/3vBgkJ/gwOBAMIAQoGDBMEBQgDAAv0APz4BgED/AAFAAYIBfcACf0F+w//+f8E/fwAA/wG/f0GCvwQAQMHBP4A9/sMBwcD/QX+Bwn49/z89QQECAACBvwD9wEF+P0I/P0FAQD6A/wA/v4KA/7/8+8A/+zv9PIA7/oJ/P76Bwn3AeP1APMP9A4FAQf66gL+9Qj+Au0RAO/5BgH5+wwMCP3x/AX19AkCBgIICfQCCQUC7gn5AAELBfn/7AH37/X7/P0O9gMF8/3xA/QICAsB9P8EBvX6+fP8Dwb6AQUI/P8JCfj8BQMFAgUI//wAAPT8DAj6BQH9BQIGAQQIA/wBAP4A9wT+CgUNDAUBBQAL/v4NBQH8/f0D/wIM/wwJAwj/DPv7CAf+BAz4BP4IBPoNAQf0CP8EAwf8+woGAgP7+P8DB/n+DPIF+/wEBQcFAfoBBQL/BAn9APcB/v0HCP8A8/gGAgT/+gICBwD8AQEA"],
    ["retained-placenta","health","+fTxAgf5CAgA9/oKBgL8AvgV7fUF8AMC/e0C//QP8vYAEAIJ//T6F/jnAQgLB/X5+PwI8vwE/P/8/Aj0AQP6AAn0BPj9/AsCBgX3Dfn3APj4+fv7/Pf/A/r78wvx8/0CCf77+Q34+/PzAf4E//j5/usEAQn/FPoJ//0FAf4D+gD1/vj1/wf9CAoICPsLAgEDAPsH8/37AQb4BAYK+wML/gP9CvgMAf8B/PID9gMHCwMJBfkFAg78Bv8HAQf+BgIM+Qb/9foBAQP4/QYJAQP3DQQFAff7/Q4HA/b/BPUGBAUL9/v+Bf/4/wAB+fsCAQUCBwH+BwUC/fD1BwX58PD8//MI+Q8B+PT79Prs+/j56/sFAu4B/vQFAvL0BQD/Cfn4A/wI+fz4AxH3/vvz+QEAEPkUA+oGCf30+AIFA/wB/QwVCA3vDQMI/AgHAP369/kB8Qbz9/IB8v3w+v358Af3/gP1+P8D+Afy//f6CAH79gr3/wQGBAL6/f//+gcE7v/x/PgG+wUHCfr+BwH//wL29QgB/PnvAP0H+AQEBAECBAYICQz/9/8CBALv+fv8///9/gAD/f0D/v39CwkF9Qz//fn29PX7+AH99gMABgH+BgMM/Pn+9QYGBfjx/P7/AgL3+vn4AQAJCAH7APn/Bvz/BAARBAMDBPYC8PsHAQkHBvoJ9/YB/fj3//n36gQG+vkEAwXq+vz3BAfx7gUH/Az0/wX7DQH2+/YT+/wG9Pz2/gYDBgHu/gb68/r7AwH+APkJCv4H8Qb9AvULDgED/vP88P7/+QD3/v8I9fn3DPEC6vsJ+P/4B/QH9fru+gcM+Pb7Af4DCQIA+v0AAPsK/vgKAPXzA/r7+/YLBwX9/QAI/Pn++QLy8fz/CvoP/w3+BQMHCQQAAggHAgAC7wED+goJAPkK/voEDwX/CAYECPQJ9Pz2+w76Av0BA/z6BwsABw0IBAED/fEDCQn++P4D/f4H9P75/gQE+gMFCvz5BvP5+/wABv4GBgf2+Pf7+vz97wIB"],
    ["placenta-delivery","health","8Pz5AQMCBAH77fMFBAT6//oM6PkI7AEB++8H/fsK+/wGAgML//n2Effn/wcLCu3++P4P7PsG+f74AgbzAwX8BRHxAPID+AIBCQX7CgD3BP3+Avv68fwGCwH59QXx+vkFAgIC8RPp9/n0+AQGBff4AvMJ9f/9F/YR/PsBAf4CAQT5/fX2+gYGCAkEA/4MCfoBAQADAQP9BQb0A/sN//4PAAr3CfgG//wA/fj/9wICBwUIAvoEBAf9AfgKBAIDBgQI+Qb++e/8BfwA9wADCQD5B/4C/wH++wsIAfT+CvYC/wQA9fYBAf36Cf7++AP+/v4EA/8A/Af+/PH1AQb6+fcF+Pz78f76+fT+AfjyAAX27AAEBusAA/kOC/XtBQj7DPD3/QICAf35/hf19gT7A/T8BfUGAe70Av307QED+gMA+hMTBA7xBfT/+wcI/wQC9/j1/gT0+fr6Bf/1AfIA7Qf3AAr19/IJ9wP18/L3DA73+An8AAr+BQn8/Ar69gQH/gX89PcD8wMC+wcACAL4BAL6/fj6AfX4+AAJ9wgDCvcJAAYHAAcDAwP8AAj0AQABBv7+AgAE/QEM//4FDP4K/wv2A/P9Afz9AAAMAvoPCQUODAsGAvn7+QANCgH8/wr+BwDy/vv8/wABBAIHAPn8AQgA/vsJ+gAHBfj2AQMA/gD/A/gC//r7/fYGAvP19QkGAfoE/xT1+wT2+vn17vf59wTx6v8C+wcC8/IR8+f89gwB/wH3BAnyAQj78vX3/+4IBgP6DQIC9AD+DwMMA/cNA/L78/H68QIC9PwI/f39CfII/gQFAwD8C/kF++79AwT+9QH/+AL4Av0K/wkBAQP9+wEACvX9/vkG/vn+DAYA/Q0H9v8B/gHv/vgFAvkJBA71/BIF/v8K+Qj7//wA9Qj7AwEIBQsF/v3/CwEJBA36AAsQC/0CBP/49/cCBfoEAQT9AvoKAgD//P37EAcB9Af/9gMBBvv7+gf+A/ICBv32+QcG/P0DAAEHBAX77v/+CQH49v3x"],
    ["shoulder-dystocia","health","8f/4EwD7//75Af4I/wLw9gIV9QT38gYO/fsRC/UG//sDCwn59e35CfXzBwME+/T9Agbx9/v9/AYJ8QEB+fT1CRP2Efn9+QX5DPz8AfkB//8D7f7z/QT7+/3y/fj1BgL2D/ru9QP6BAYLAfMOAwL0APf+BAEBCvQEAwD7AQIAAfP89P/w+gkO/gcL9wMFB/sE/f4BAvgJ9gYAAPwJ+gkACA/4Cv0GBgEC/fj1+wf++/MC/vz7/gEAAvP7BAX+CvoB/O379ff+BP4CAvj3AAD++wAD/f8CCgUK/Pr7/gIGAf8L+QAO/AALAvn/8ggM/PL6Awf8AAkF9Azz/wL9/fQDBfv7+AHxAPgG+/f2Afz79v/+D/EGAvYGB/ztBgf5CPv2+gEL+v/5+xL78/kJCP369PMI/PP5BAf58OkC9f779g4QAAf/+/35AP8C/P0E+fr3Bfb0+f/9CgT0/vQA+gr59BD2+O4N/AH5/Pj8Cwjw9QP6Bf0EBhX2/P//+wX3Awj0//X28gAKBggIDPkCCAH/AP37AAL8/v8A9/UFBPIIDfkA/Ab6Bgr4+QLw/AAI/f75/wMMCQEGAQYCAf8ICQb1B+z3BfkK/AcFAv8GCf/8/gsABv8CBgMIAvv48gX8+v7xB/b6BAL/A//9/fH+CQ75/gEB+QcJ//vwAff8/fT0+wbs/PwJ/fMABgn9+QD+/PkG/xD4/Pz+BAb38wwT9gzz/QMKAfb79PkN/OsCAAb18QT/B/f7APMA9/z48/kG/PsFD/wO+Pny/wQJB/YD//wC9gf7/P4A+hT/+wX0A/QQBPsOAfvsDQABBQH2ARUU9/gEBgMBBQoM9wAC7uz/CQj58vzzAvUABgsGCQv5+gYF/wf++gEB//37Bvv8/g/6EfsFAP0JBQkAAP8D+v39+QH5Af/9BQsJDQEF9AoCCv8P9Qby8AT+AwX8Cf0J//z/Bf4IAQUA9/sFBgUEAAIH+gQD/fj0AP0BAAMC/QL1/QQI/gb9B/X6Cf34//z8AgX2/fz1"],
    ["breech","health","+Pf3B/cJCAMA+v0AAAL5BgAQ8gP/8wYE9/oDBvwT+fv4Efj6/vn7Dvft/gAGAPnxAwf49PsC/Pv+8wQC/P7yAw36Bvv19gr8CwX6AvsB8fQC+/H7CQMU9vIA9wPz+P32CwL55wz4/QD8+P4LCP/6+v8F/f0CG+oCD/YD/wQH/vf7+AH8/wIKAggEBAEC/AX6BfgAAfsC9AX+/vwM9Qj5BQH7A/0BCQD7//kJDAEFAvwG9gAD/AITCvwFAAsSBvYA+P4G8gAFAwMI//n5CQACAPX++wYHAfwGBv3zAfgEBO8A/AQH9fwE/v4F8/YFDPoEAAT+Cg4N8/78/QAM9Pb8Bu/y9AH8BPYFA/j1CwH+9fkBEPz9AvEAB/zo/gvzBvX4CQoB+vr6/xEC+/YDCvv4BfwHAvH6/fH99/sC8gz6+ggF/gL0A/8DDQMN/fz8+Pr2/P/29/75Dvf6BfgD9Prv+A38/f0U/vgE8/v9Cw7vAgP5AAD1BBf68f7/8Qf8BAP79QkE7QEJ//8ACgH/BgL6CAT6Avz6/fv+/AIJB/YQAPr++REFDQf5+gn2AQEJ+gX9Dv76CvYGAAUECwEIBgP8AvL8CvcB/QYSAAEGCwcCBgUG+vsA/v4KA/73AgbzAAYBBf0ECAD/BwL7/vr4/w8A/wEH+gUVCAD//AL//fYA9f/v9/YH8v4DAvv8/ggA6PD8/QrnCvvuBAr98gUA9A0A8wIF8f8C9PUM/+//Af8GBAP5BgP2+AkE9/v+BvgGBe0OEAcT/Ar4AwcRCv8C9vf88P4I9u0IAgb2+AP5AfX79/oB+vkBAf3xBv75Af4FB///+wz2/QkU9AIUAvX+CvgC+/H+/vME/w35BP4A+wX/BwEI/wX9+wMGB/kEBAn8FQH8BgAO+gUC/Pr+8AoJ+wT1AAcCAAEBAQwA+AIIBgAA9gn4Af/1APsFBwUI/Ab//AIKA/7+Af0JCwcA+PgJ+wMA8/cABwcA+ggD/fz5AwUE+wP+BAAJBQP+9wD5BwH2+/wD"],
    ["rupture-membranes","health","AQUDA/Xz+//s9+z8Avn9CgoOCQAA+/Pz+vf4/vL47/UFBvv2+PT4BfL9+/QD/RgLB/74AgQG7wH99/36Cf0D+hQRAfT++wkCA/n+BAbx/Pb6+f0FBfwB/P8G/QQBFvoBARECDgUFBRD5+fwF9gIJD/v4+f358vkF/wL5Bfr8AvsAAP4CAAEG+AMD+voHB/n6/f/3+Pf+/wMDCgcG/fsIAfoIDwgG9QoK/f4ACwUBAfMBC/n0/Qf+AgUL/voN/gT4BQL/8fz2CA37Cv//AvUK/BEC/v0BBAkEBvgD+wAIAvj/BQYH/P79A/QCBggLBfL2/QP+BvoAEv4K9wkN8/r+8vH/9wv18fEC9vby+PP/BAgHBvgKAPH5AvjmEgH+/ff7CQD+B/r5Ag/2BAIG9fgKDAf9CP8K9vru+QD//gf4/gIgBAT1C+kDAwQD+P358/cE+O4J//n/CAHzBPb/6/78AP0GAvUB/fb/9f3/EvMH9Aj77v8KAAX9AP4D/gMBAgP8+AD7/PsLEP/7Cf/9AQUCAv0D9AD8/vQP/goJBf4B/gECBg4L9gTyCAT9/vz+CAf8BQYBBQYF9/4AAgT7+w0BBgP//eX/8wwD/QMFAwEC9wL/+QD7/wgG/QD9/wH7Avn8DQf7AP8BAggFCf8H/////P/68v0ICv3/AAgC/Pb7A/32+gMN9vj/Bf3u7fwBBe8JBQMA9QPz7QUM9w4K/QHrBAUFAf8D6PwL/vkHAgwG+wgDAPL+AwD6BPYIC/MA9P4FCf8E9ez2/Pj+BOn5/PwABP/3AgAH/gUN/wDpBvwI8PUJ+v8CB/gDCgbs9wj2CvsN+AII+AER//sB//sF+vz8AQD3A/f7+AAFBgwAAgkIAP3w+v31+wX6C/wHBwQJAAL5APwCBwkG+/z8+QEC/AgOBf0CAf0I/vkB/P//BQT2AP0DBP379vcAAgAJAAACCgf8D/z7/P8MAwb59AIC//UF7vf8//3+Af3/9fr1Af3++O32AfUDCAMD8vwC9gHs9gf7"],
    ["preterm-delivery","health","+f3x/u/7/gbv9PL8B/f6/wYS9QL99O/68ez9DPL/8vQB/wkB+/fuEfr2A/QD+fwF/vwB8/kM8vj28v79DAYEBhIPC+r89wQFCgj8Bwr0+ur29vX8AfwHCvcA8A32CPb8BgACAwv8AQP+9gALA/v5CAAE+f8GCPv7BQsDA/j7CPr77/r7BQL+BgUF+fsEB/T+Af/7/fX+/QH+AwUM+AYF/wH+BAIK/AIBAPb7BQP/BvYBCv/+CAYDBAAK+gEBBPoDBQAL8f74CQcIAwUFB/UGCgH4/v/3BAoN9/b8Bfj9Afj+AP8EAP3+/f8C/Qb1BPX6Afz8DAL9B/H9BgX68/AA+vr47P77+foA9fH4/v387wDyB/kG+egSBvTvBw7xDvn3/Qb6/gP1/g39/BD7BAT9/gAK/QD9Cvv98/v9/wX29/gODgL5+PMBBw4N9//38PT7/Pvy9vwICQP2DfwC8gX7AgDyAPkG9PgL//vqAQz5BAb8/P/6+hX9+woCA/sCCgcG9v399gICBwkF/fj+BAACBQUL/wTzAvoAAQj/CQUNBAIBBQ//BAIH8gH7/QX5DQb1Bvz7+gn3AQL39vL9+wD9AgEBD/b59wEDBvn7DAUGAAQA9QP9/g8CCfn3AgX++v/2/QAFCwP8/wYM/f3++QL5+vz39wIIDAL2+P7++vT/+gYFCf7//P79AgL4A//67wH//PzzD/z58vvn7gX6BAzu8/30AQb9AvsF//IFAgcD/P8A9w0EEwrz9/P5/vb/Efb7GAD7CAL2AP0H+/4BAPP96Pf1+gL67wQB8wECAgEFBAj9/QkHB/MPBP3/+wr5BAAABff7/wQD+/YEDP4O+/j8+vr0/fYE/A39CAD98gAC/QX5BP0A9/7/Dv0EDQT6BgwACgQF/QEE+QT+/fTyC/f/A/oO/wT9/wkIAwQJ+QYCCQT79fzqDfkQ+v8H8wIDBPMKBQEA/wMACv/+A/b99gQC/QgE+A0C+wb7AQcCBwML+PgK9AUFAv8H9/sECPny9wkC"],
    ["uterine-rupture","health","A/r1AP7o6vv4CPb7Ae70/QgK+gjt/PP3/vcCEfMI/PQE+v0GBQHuFAbs/QUJAAMGDAX/+Pn89fj7/gIBEQj9CB4E//P98AAIEgr+/vX09uj4//MFDfP5APP4AQH3CQgEAPQBBwv3/APk/wwI/voBBAcAD//z9//7BwgJ/f0BBAD3/QEBAwP4+gUE/gELB/f9AP3+AfQFBAX7CwYF+gQCCv8NBgEJ+gUBAwD//wUBBPoIBwoFAQQG+gQPBgT+BgMADfoI9gX8AgQHAv0HAgoB+/sBBQH6/AoFAf/2BAACAgHy/gL/AQQGCQH9//76CAD8AP8EBQYC//n+/AD//AUH/+/69v4A4v/29wHv9QD9AQQM/gYG5/oBAPj1/gvwAOvuA/wAA/wB8P3+9wcG+f3+DP8CCAEK/fX2+/35BQv6BwEYEAb0B/MBAgUBAAsF9gL69/H4/gb0+gHvAgX3/RYF/QQAAf0F+QkI9PwJEQX/BQv3/Qz5CPMBBAQIBQYP/wL5+/T5BAoKA/38//v3EgL9/QUE+vP7/AADBA/+DvoABgQH+hACAPcCCAoK+QAJAfkCCAoABAIJ+v7+Dvj/9ggE/AQAAfEF9gYJBAb7/gL/Av75/AQD9QQJAgAE/gL7BgL99AEFAvb7AvoD///+CAb//Pf6/A4DAfcGA/kCB/sCAvPx8gAL/eL38/v2BgsJBPoA/wT8BPcI+QQC5gIR9BT29woJ9/wJ/PAGCf0EAP//9QQECgv9/wf19QIED/74EP0GCgIG8AcO+/EQBvT18e/5CPkC7QMB9AADAwQGAe/7AgEB7fj8AP8AAfUMB/wEBPv//Q0L+vEPAvr1BAQA/wj5/fj/Avj4BfgE/wgAAf0J8gAE9gPy9/T9AfoG+vn7Df//AQoBCv/9/gMK/wX99wUDBw79CwH5CQMDBwX/CgoO+woI+wf9/Pn2C/z6BwUCBv0HBvwCAQL8+AMFA/wH+QUH/wH9AgoEAAQA/gX5/wQDBPX9CgcFAwP++QUH/voEAQP/"],
    ["newborn-infection","health","9AH5CAHy/wX28uwG9AoC6fwT9/QDCQH58voGAwb79vQI/gEACQX+Dfj6CgP/APID/Aj7/P/+Av7x9/32Cwf4/Qj/AP7/+v76DQIB+v4E9P35/gT9/PAFAAQQAvH7/Qr//vjoCQMGCvj7/AgHAvABCggB9fn8FPz/9//0+gYE/foKAvj5+QL6FgAK+wT86gAG/gLx+v0L/AD9+QkRDAEA+v4M/fwA+gwG/ez9+/oM//cCBgH7/gT/A/v2AAIGAPMMBO8KAff+AAf+DvcXAf0IEAn8CQABBwP4AfsL/AUB/PUA/Af++voHAgMCAAn7Bvr8/P0F/wD8+/j//QH9/Pv/DPMD8Qzz/AYH//LxBAQA8QD2BfEABvf8CgL4DxXpAP36CPgK/Pb0AQkBDQn2BP4AAv71/xH6Efv3+fEC//0EAQkD/gT69/8K+gYB8AEC/Pj0/QX1+gQNDf7/APMM/ef86wn98fsCBfsD/ukACQX79v32E/74AAP5+/z/BPsECQAA/Qb4+QMDAAkDB/8CBgb++wP3Afz8AfwM9PoF//wBBQEAAwYIAgIL+v3z+QQADQIA+wkEAgX//QX+9P0M+fT6CgIHDPUABwQKBwQNAwT3BQkCBQgGAAb+/QID/Av7+f/0BPsE/gz9+P/5//IK9gL5+wcF+xgCCf///wP0A/T9AwHp9fcK9e8HDPr86gb2ChL39APq7vII+Pf68AwH+wP/ARcAEAEEAwUI7gD5BQT9+AP0//QG+foB+fL6+Pz2BhL5Bfb8Agf3APACAPP6CPr7A/wD/wr//AL4+QH9AAz79P8D/e37DfoE//3r/wX6+AMBB//7BgID/fMH7woF+/n+/AkIAPL5EQUM/QwDAQb29wf9//0BAQkE+/P6CgYIAPb5BAAA9AQCAPv57f3//gIF+vsJ/f3+CAMB/P0IBgEA8gX/8gz/+QgAA/8BAAkCAQQFAwEGCQgFBQEB//n//wn3AvoHAvUJBPz7/AAI9/4G+PgGAfoABAEF/fv6B/4G+Pj2"],
    ["newborn-low-sugar","health","4/z7FfL2Ewb8/fAL/wEC9fz36/T//fjz/vIIBwAB+vwACwD9AgYACej9+wQA+fYA+vf68Qb9BA7x/AD5+Q38/g72AfEQAvv+D/b4/wUH8/P9CfgD9foM9Qb5+AX6APkOD/ru9wX0CQoF8AUR8gb3BQUD9PwICPv+DQb4AP4GAP0EBO3zBQALBfoK+wIEBPwF/fwBBPwDAP38AgUL/QcD+fb/C/X7+P4B+O4CA/sIBv7xBv/1C/35AwP4AAgB/e4A9vj7AgEGAQP+/wQBAv4EBAUD+Ab/A/n6APv/Cv0JAAT+/f36AwQFBf0DA/wAA/n5DAH8CAIA+/z5/gn9BvkEB+n3AA70+AIB+vjp+/gAA/Lz+fb79gX7BPvsCQr7DfkCEQ4O/vP9CgTzEP8K/Pz2Be8M+e/69QUA+f7/BuUFEPgO9wP/Bv347QEB+vsH+wMDAAX7+fkCAwH39/QBCvH3/wAI9fwN9gD+9fMFAPsAAAUQ+/YLBQcB7xD3BBL7BQEC/f75+v0JDAECCAQCEP76CwD9AAn/AQr/9vsMAwkE+/oB+Qf9AgoD/gLyAP7xAgH6BgX7AQcD/gn+AAUNAwj2AP39C/b/BwX/BwACAgL+AgYD+AMCAgcLBQb79gwFBf7/AgIG+wL79fcB/vn8/gn8/gYG9/4DBwP3Af8G9vkCA/7s9Pn78foJAwwC7AcB+fz/Agn78v35/wX3CAIK9gLz6AAEAfn3Av0I/PgFAwcF7fv9APft/wX8/wgGBQn6FPf3BAAL/gkB+vwD/Pn6DPv49gUK8vT2/RDz9wnx+wED9f/79/75Ae4IAO/0/QH2BQgDBgv6BggP//wFBPMB+An5BP/3/PUDAvoEBggMAAUEAf0CBP0J/AT4C/r+BhMFCQQCDv///P0IAAL4Bfz/+wwH+QT++/8FAQT39v7/E/wG+AL9Cg3vAgX9BgT9+xAJAAII/P8D+gMFBf4EAAIE9AX+9/wFA/v88AIBBPn6//sD+voD/vcIEAT87gf77gLv/wED"],
    ["postpartum-infection","health","+u/1/vfd/wkB9u386hEGAAUN+/0F8vny+/4OA/kG8/4L+QULBgb5DOz5/ff7/Pb8+wUF//gMCPz5DgQEBQb1/vX7APEF9wwF9Pf5A//9/PUA8gb3BfcM+wMEAwQD+v72APjv/QkHEfn99AcD/v0J+gD+APr/Agz9DvP9//v//wT7Af/+Af//C/MK9fD/AvUA/f4A+AMD7v/+BAgO/P4H+QP2CwIDC/b5/wD48/8KBwAH/PwA/QcCAf4M8/3//vkNBQUE9fn3CAT5BgoEBv8FAgP4/RD7BwIC/A8J+P/6CP4A+/oH/AIJAwL7+QEE/vkBAQbzAQEC9/j3BfQI+wMDAvXjAvnr4voC8/vx9Q7+/un+Bvv69fr4+QXtCw3wBgr9BQX5/Aj/7hT95vYACQr1BQL59vP5B/L4/wP3Cv4T+AT9/QT+/PX+AAQFB/7++fPwAQ7+BQf2AAf8+fUA/fv4AwP+/QEB+PYF7v4O/gIE+fr8BQYF9wYB9hYAA/z7AwUB+PoD/wQKAwMIAwABCwf2CP3+AQT2CQMD+wUEBf8J/AYABAkBCAgC+gT5AwX8BAn6DP0DBQAGDP4EBwYFBfn8AQMCBf7+Bf8ECAYFDQcLAv/3+wYB8gMHBgj++Q0BBgwA/PsLAPv/AwH9/gIKAQj9Bwj7/gYLBQP2/gIBAP0B/wHv/fYA9/sODwHx8gHv+wn//QP3Au8A/fgJCRIFD/oKBwTzBwsM+P0F+PnvAhMCAPD09/8I/gv79f8D9gUQDQcB/wD9+gH1+vP//AIJCf3sC/X6AwT6+PX3Af3+9A0HAg4B+Pf8AQgPBPbsDAH9+fYCA/wK+wULBPoO8gb2/vMO+fgAB/4KBP4H+gXz+An59v34BPkACwYCC/37Bv0D/fcEAwT98AcGAAT9+gL++P4C9QP4CAD3A/r9AAUIBAj/AQv9/AYKAgX9+PoIAAME/QD/+QkEEgj8/wH+CAwAAgH3+/YN9v8BAfr1Bfz6+gP6+/8E+wT/Bf8G7QP7+gkA/Pzz"],
    ["late-postpartum-bleeding","health","9vz8AgLy+woCAvsHDgUDAwQU+fno9wb8Au4MC/0J9voGCAEDCgDzE/br+gIG9P4HAQX+7wgAAfwD/Av9AwX3/g/1DfkC/wIGCg7y+/kBB/Hy+v8EBvsM/QD78wP5Cff8C/P3+AUD/v36/fsNBfsBAgID8w8E//72+fX6/vf0//Px+wAH+//4BhAGBgQGDwMDAfsBAfn8AP76AhAG+g39/vX3BAIU/gD/APMFCP4FBAkE+gQEBAcEBgEP9Q38BvgD/QUO+AH/AQT9BQQE+/8AAAT/CPr5/hAE/v4ABf39CAoG9QT8DfcCAvv59fP8CwMDAf/6DQYD9+76Bf388+4I9/38/wHu8/AK6fHuBgX2+/z6CPEF/vUD/gj2AQz4C/j8AfUM+/j1+gH09AXwDAIDFAsA+AIDFvkIBAEDCAbu+gj8/A7nAfsJFwwL/P4B9gEB/ff2C/3zCv3/CPIE8wj/8wH49/f7+f38CvIJAREH+P37Cf/5BwT8/gb/+PkQ/wn99QYC+wD4DP8D/ffxDAYC/wf0A/8AA/oE/QT7DgL++PoE/wAFBgEFAvv6BQD+BAL//wYFBP4F/gcBBAAJAQj7CQP5CfkABwcKAgYHAhIACvkB9gEG/A0FAvwG+gEI+wX9//78/fQD//v4/fkHAgUABAACAAwJCP7x/wL+9/r0AAAGBfr5+u/q+fb96vsHAgIC/AX8/OT8//wE5xD//P7y5QP5AQYU//cL9fIA/wHw/Qb5AwfuAwv/8/kAGQAFAfIAFAEH7AgK/AQJD/v7+f379PX5+fkJ8wH79/sB/fYLAQEF+f4BCQAK8/f5CQ4ABQgGAgX/AgMABAT/BAgF9Pn+CPf5BAgF/gEI//8F/woK+gH//PoB9f0EA/8GDAL7C/4C9vX5Cg72BvwD/gQIAQEFBQICA/r/Awf+AA32AQYIBAQHAw31BPsL/AEAAQ73AvoD/v4LCvwCBv0A+/0I/v3+AP4DAQQFBAH//PT9AgEE/PsHAfYD/QT+7gMI/QQA8wP6"],
    ["gastrointestinal-bleeding","health","+gEBBAHqBv0OCfv3ERwDAwAD/vb5/P8BCxD/+QwA+f8D7vb+8gf6EP4E9wr69gT8/fsS5xIABvsHCw0KAxD6AP3+BQAGBP38CfUQCfAHCPwGCf0D9wgG/w36//wLBfT+AQH4Bf749ADmCAAP9f0I/xQD+gH9BAkBDvb/9QP59fEABQ4K+P/7/vkC/Qz4Awr38f7/BQr+Af37AQgDAgEL9AL5BfoSAvgJA/kBDPsACf76/wX9A//++vX9+P79+fUBBgQHAQMHAQEFBgb6BP8EBv7/C/r5+QP2/AQLCf8EAQf+AwT0/vf67fsB/AED+/32APr6+fkACv36AwIA+gEDAe4F/Af+8QL28wn09/gAAwT5Cv0NDgIG+/r/9woB/QEB/vP2/e8F/ATy+vPwBvX48v0b/fwK/AUCC/IBEPsG5gIM/AT2/wgMAP78/f7+CwYCA/z9BBQDBQQN//b78wkB+hMBA/3//wD7BgkHAPr9/xoR//QP+gP7BvoE//kI/gzv/fcBAAoDCQYPBfgGAgkB9AX0/gj6/P7yDQz+C/v5+/8E+xH/APn4BvH7///5/gAFA/wN+wP0AQwB/P73/QMAA/r/AQYA/wL5+wUC/QUBAfT1+v8C/wgB9/r+/QMD+/3+/Af7BPYDCwL+B//7+AT+DQMC/QwEAPQI+/z2+QoIAwX18fb79ur//vsDAf4C9/jvBAMG+//8+QoLBPcGAvjxAPrw+QgDCvQR+Pr49vzy++8E/gjm/f75CAUGBwAAFAUCEf3+8wsA/vQC+gr5BQ/zBfz7CPr2AQMDB/nz8wT/9vUGB/kH//MS6/v6DQT0BgELFgUEBf70AP/4/wL/9/j2+AIA/hEHAgD6+goB9vz/C/f8Af4NA/wE/gD7/wIG+vwL9/cE/gL19g4C+wIC9wb3AAD3B/r7+wbz9QIDBQP4/gQF+//4B/z+Bf8J/wAH/v8M/fv+EAkDA/X8Av4MA/778AMJ+gP2+AP6Bv0DBgMFCPMD9/kA+wAA/ff28fz//vwB"],
    ["opioid-overdose","health","/QD5/vH1Bv/26vUG8An9BQAI+foCEAH0Af8JBf8A8u8FBvUG+/8JAgoTBPcF/gwH8ggSBAH9Bv8FAwz78QQMDgEB+e8A9vP6B/P8/QER+PgEBfXwChX5CAAG+wYE9AX+CA79B/8ADP4GAQQI/wD2BPcE/gP6CgAAAgUI+hMI/f/1CgIHCvHzBAT9+QkR/AUBA+4AC/39AQD+/AL+9v8B+gH+E/0BAxP///j7BvP/9P0CE/z/DgcJCfz0+gL7AQz6Af/9BBADFP8JA/XzBO8DBgIHCgEFAAP6/P3//wL6+wD7/gH6A/71/QMK+fz//wH9+/8EAvwJ+vsB/fr+/ggCAvj97AMC/v4CA+zlCeoDDe8EBgvzCv4M7/MDABoH7vjz+vX3CAAJBQr3+/Xz8wH7EQf/AQYIBA33AAUF+QABB/kB+Pz8Bfv8/xL/BwL9APL+EAAB/wQE/foCC//4+voJ+xMQAAUJ9fn6/gkI/fv8CvcLEfcDBAj5Dv349fz9BQD8Cf/5AgP9Bwj8CP8CA+8EEQr6Av7+CfsFDfsDBArxBf8CDfoA/wAJCQD89/v7Bf3+9wYB+gMEBwYB+Qj8+QEKAgP7Bf4D/AcEBv/7Cfr4BQIHAvn++fsF8voC/gb9BAP4+vgH+wkHAv0AAv4LAgkB9AL3Bf35/Qr3Av75Cgn9/ArxBv0W7+//Af/x/u4ECPL55Q78BPoB7QMW/w7//f4C+PT3+/4FCw3/Cwjt8hEH/wn8AwcL/f3//gIG+wQIBPgB+AkFAwcC/RIJ9QAKCw0C//gHAgr6AwYCCwQB+v8C/QgL+wALAfkHAgUHBgP4CPoA+AYO/vf+8gEG/QD0AxkA9fEC+AICBAEI+PwEBP38/PkB/vEA//8F9v/6BAkA/AMLEAAQ+fwICP/4/QL59wv++vn3BPMDAg4A+/ICCQD8+w3+A/8BAwAC/foE9/v87gn/ARADBgEGBAH8A/n9BvvzCwUJ+/oM/f35/P0FBQ36APv+/AMEAwL+/wH+//wN/vwG"],
    ["spinal-injury","health","5wT+CQHtAe7u/vcS+wH/+AL8BwbsCP7+/fQDFwEACQP++QTvCPoEBAQGBQz+/gMLC/oF/QL5+wMK++8F+gT7Aw3vFQ389u4A//8DAv/2Cv8BA/L49/36/f8EDesX+QUBAQL3BAUFCvP+BgoA+AbwCQMJCOv99foB9Qr+9wrwBvwEAgL5DQAE/P/++/4BAgL+Bfv6AfwJ//8A/AABC/r//QEFC/wC+gsA/hT9CALr9gf/BvQEBgj+//YAEPr+/QUH/vMC/QL9/QD/AfwI9wcLAwUG/wz2Bf79Bfj49wgBAAH89gAG/vwD9fz5/gL/BQABBfoDAwgDBv/58v7/+gX9CP35/Qbx8/7r8wAB+vj4/ugCGQ319AcHAf/9BAr48f79//j8/PgE+e8BCf8JAwX9FvMKB/0J9w39FgD1BPzw/fsI8A3x9vz8DQkBDfj5BQEA+Pz18vzy9QEEBAD5+wYG/wn69gwI/Qb89QETBw/5/f0HAA73B/0C/vb2+f8LCQL+CP8FAgsB9gD+BPT1+gL98/L+/AAF/QH7A/8GCwsJ+QUBBv0BBfsMCw0IBgMCAv8I+Pv4APv8/gb6BwQA/gn+CAX6/PwH+wQB/xf5B/7++f7/AQgBCAH89gABBvX9/fYE9f8B/gEC/QX39/kCA/n6+Pz9B/8L/fX6AvcGCP0GCwP3BQATAfn99PkK/RX9BfYE//z7Af/5+wTuDQYS9gT3/goNBPIF+Q0EBgTs/PMF/gcTBAUQ8/wGAAr19AgDAQkBAPkNA/r59A7yEPwK9vb9/PoB8/UGAvz5BAYE9gYE/wER/goLCQr9EA8HBwcOAfgF+PwB9wIB/vgA9fYOCPD3BPoBC/sHBPwE/w78/vf+CfgDAQj08wgDAwb7AAgLAQTw/AkH/Pv8Bf0IAPj1//T2A/rz7wQIAQb08fz79gUH/AD/+PoC/AAC/P/9CQv3/P4DDAIEAgD+9QT8APv5Av8B/AIB+PQBBwP+/BABBPn6//kGBP0AB/4A8gD18gf3A/4C"],
    ["head-injury","health","3AQCEADxAgT/B/0J+w/yBwQO+wAABgj/AwgICA34/gD49gUB9PEDBfrxBQ7y+O73BQfw/wsCBQYFAPT5AOz99goOB//y9wDzAwEACQb/AAQLAPr5+Q4JBwv39gH6BvYEBgD6+PH/CAD/BgACEQT3DQYD/Qf3A/gHAfbzAAQH/v8B/QABBP8JBv8RAQb1DP79+w0C/wIC8f8D8f73AwT3/QX7AAr4AgEHAwUA+fr6/gEA+QcEBf0F+PjxAfcH/AcD9wT8Df0HAP0B+AD8BAEM9/oI+vf9+//+BA3x9Pn/AfUB//UB/Qv/+/8O/PsHAvcHAf32AgsO9fYA7QP/+vj//+n2AQ3z9vz78PnwAe0QDPzzBv8K+/78/fP7BgD5D/z3BvwEAvj3DPz6AgMHAfYD/QoS+AcDAgz3Aez6/u8HGAAC+ggLAwUD7fwG+gUD/vgMCwHxBQADAQMD+/H4//4M+Qj88fsQAf749/r9+gYABgIN/voO9Pb7BAT3AgcB/wH3C/EK/AQKCQsJCff7APv8DAT6+vz+/Pn///MFBAL9/fv+/AX8/P0K+gT1Ae35Av0E8/4EAgf/D/vz/P7+BAj+/Pv/APcB+vf7BAUB/AMFBAf8Bf8IEwIAAfn/9QQEBfv9AAf7//4AAPQAGfr/AQz1/AkJAvf8BPn4/fP//wT9DAPi+QIN9/UWB//88gX+AAABAAkA+PD8A/sD7/8GAg7zAf0HA/T9/QUEAu0D+Ajz9O74DQACBQUD/BD3A/8G+P4HA/QA/AP5+/AC+vYDBQT3+xH2+vn4B/30Df38/vcO+vwFAf74CP/0BgD//wD+8fkZAgUFBv8F9QkK5wjv/Af/7gf9Cv0BEQkCEQj3AP3//gAE+AUIAPr4+gb9/gX2Avb+/gYK+woBA/gB/vYAAv749Pj5/w3//gYM+AIIAgAFAAf38woBAwUBAPv69+4BAQL6+Ar6/goF/gQCCf32BgP9/wH+AwcBBgH6/AsB8Qj1+AECAAX9+wcE+QQA+Qb++/f8"],
    ["amputation","health","9gz2FP/7Bfv/DwfrDAb5/fwSAgTzDAYJ8/j5Dv/09vMB+v7mCvkF+QH//QQJ9QAWAu0P+Av+/Pf/AgICBAME//7y+fr7Df/+//30/fr/+vcBEvn4EfIFAAEM9vj+DPgL7wkC/AgI+QMJAwQB/AIL/AAE8v/2/w4A+fz7CfUHAvUG/PkK9f748/8HBAMMBwz9BAgH/PoDBP/6AQ73BQ3+BQII+/f5/v0D/gX7/wcBAQDuBusH/v/5Dv4BCvgJ+vUECw0A+gT8AQD9+wH//gEG/AkHCvP/Bf8N+fr8+/7+Bv//BfsC/wkI/vz6AAT7AfwL+QP88//6+gH5Af37+QAO+/f+AwQA9f7vAwj8+wMC/wYIEgoC+wMJ/Av18w8E/gIE/wAD/fkK+/v2B/UE8vkNFAHxB+wFAPX/CgAGBQL/+AD6Af/o+wj19PH5Bv/6/gnvA/r2AAPw/gkG9vwE/AoPCfwMBPAL+PoACAYCBAP1B/oP9fsCCvb4Afz39wn3BQbv+f0FBvwE+AcHAAD8EA4L9/r5Bvr5BfkG9AQGBwkS/f0FCQcHAAEEDvb67gAP+wH47wH2A/8N/gb6/Az++wf1+/cJBgQCAQr9Bf/6AP7/BAoLAgz/BgEABfcEBv4CCAgDAgf9Avv4/QX19QoD+AP4BAAJ/foC+PD7/gcH+/36Bv7yBwMPD+4B6vP++Ab7AQgIBQUC/fAAAQYG+QIKC/j2B/sL/PYL9wH8/v779fTyCgT1/QTrBBP+Bxj+DgEKA///B/0C7QQBAP/3DfH1BPj7EvTz/fr/AAT7Cgn0+AX+8AYC+/r4/v/+9vcBDgn/+gD+EQAEB/33Aev8//70/vf98QMHBgQAAAf7/AIGCvsK/AQBBQIJBQ38AgICCfMLA/4D9/f9AQH/BwoKCQcH/gMCCPz9/gP8CPUECBH/Af8D/vr2BAL5/wECAP3///z2APUBCfgFDgv+CvL////2CwHqBwr8A/8I9gAE//cD/Pz2/woS/v75//38+wII/QD7+AUC"],
    ["crush-injury","health","9Q4EHf7//Pf3BAj/Bf/zBv0BDRYDBvgC+uv8EPX47/wW/f39Afj/B+33/AsfDP0AA/0T8AwE+PgG+vb8BgT/AAP7/vsI/foE/PL39Pb0BQXuAwj5/v8DAwAACfsIBvj+/f//AwYMAP8J+P8MAfsFAfoC9QIG+vzw9vkN+gL4CfH//wIBCAUM/fP8/gv6AgMGBQX6CwT+BvD9AQoL/f7/Av8FAgoB+vwEAfoDBw37AAv7/vQG8//89/oEDvX58AAKBPrz9Qn5CQUCAfYD+wTzBgQLAvv9AwcAAfsCAP4CCPT+A/UD+AP//QcF/gUCAAL/+QP+BQIBAf/2+QD0AQIDAPEK+Ar3/P72/hD8BA3zAAT7ABEH9v8J+/z+APwH+gIBAQv+/A////r6+wEI/AL4BQEJCvgFAQUKEAYI+Qf0+vQN8Av+//37CQ/+BAX1+P/9+wsG+/z69/8AAALt/wz6Af4B/QQA/QTxEgbzBBb8/QAGCAPxDvAA9wfyBRQDBfv//QP4EwIC9xEF/QYGBgAN9QT1/P36/wb9/vcP/v8X/v34/wEHAvwWDQX9AQYMBuwEAgH8+f4HAAECAwcA//r5DfkDC/oC/fv5AQ37C/kEAQ36AwH4BgEEBfAB/wf/+Pv6/woEAgXy/f3+9vgEAf74APj8DAP9+PXw/f0JDAYBBv3n9gAD/vUJCfkGAAEC/Qb2ARENAPkGAvcC7vYR9v0L9v8GAwP67P33++78Bvr99/77+ggC/wQCCwUaAfv/+fwP/vkFBP3/8/sJBAUB/+7z9AYH/fMCCPzuAO//7+4G+vn5CAH78/3vCPf5AQ8G+g0Q+P8A/QEI9Pb89/gD9Pv+BQgDCvn5CAv89gAKDQcHAQMBAAn/+vgH/vQCFv8HCvb0/gwM/AL+A/X0/fX8AgMD+wEH9QIQ/wEFAQII+AMJAgcBBvr4+wAJBP4BAQUA/f8B/AwN9QoIBgcBAPz3/gf8Av8GB/4B+PT8/f4B9vn4AQH/AwEDAAkACQAC+fn/AQf4"],
    ["entrapment","health","7QIPDxD3/er1+PECB/z3BRD+CggCCgAG8/cM+/0B+QUJEgv///UQ/wj3CAv4BAXy9v7vBQrx/gIGAvkG8f/1EQz/9wQI9gcA/Qz+9/3yAf8B+AH+5gz27voAB/H3BAD+AQMA8u/8AO76BwIJA/0DBg3/Bvn27fT99/3//gkAAfkCBAcABv0OAfMHAAn5BQP5B/oABvb6AP8E+gXz+wHy/wMF+gj5Ag37+wD5A/Tz/QYDAvYGBvv4BgICCf37CAb9Bf0H8wb+AQEM+fr9+gEEAgr+/gIG/AL7Bfn9+AQI/AH7A/4HAAT7+//4AAAL+QEG/Qr7AwUKAQYF7QD6BgH/Bu0DAAD/C/gB9wgI8wbu+voD/QP/9/v8BfnvAAr//hD8Cf4G8wX+AA/8C/YM/f8ACQIOCwIUCv4F//oI+wHx9P0L8f8A/BAFCe//BfD8CPoJBvj/CvsA+QXu9xr0AwwHBQ78A/kL+w7xBgD8B/348vT9B/gC//gE/Pf2BQAK8PTwAAUGBAr+/AMC+/z8DQEE+QQABQED+P3zBe4P+vQA+vsIAfUBBvz4DQP8/gD7APoI/gn1/wEE8gDuAQsE+vv3CQD69f8D/fz6AgL+/vn//vX8AAj+CfoBA+oH+gD//v/7Bff9/gT6/gIB/vn7//3+AgAMBQ4IAQP79gAN9Pr6BQXtCgoeDPL/7vnn9QD8+f8HBPsIBvIIAQMG+QQQAAEKBPwLC/QC8QIG/fwFDfcJ9Aj8A/74Dgv/DAMCAPL9BPgPB/YFCAT0/fwEAPf8+/YGEQHy+v3t9vjw//wD8gL+BQH3AAH+9/ny7QD+AwDx/fgLBP8EBAD1+fT2CAkCAu4C7foDA/YF/wb69gD3BQAJ8QkHAf4D/wAFBAD7/fYBAgEAAQMBAgABCQQECPj+AAH+Df8B8wICBvUB/g0JBPkDBQn49/4AA/IA9/UA9vTzDP4LCPj6CAH/AAMF/P34BQX/CQf8/w4F/P/6+PkCAAH5+wsFBQT6AgUCAvj//gkC+P72"],
    ["nosebleed","health","/+/9BvbsBgYK+PkIAQkA/fQF/fr69AX+//j4DhP09PcM/RAKBgcO8wH/9vYD+Pf0//v69PX//v/6A/4BBgP4+/EA8v0MAwz49/rx+/8I//XwAf8V8QwF6gcLAQMK+f/59P39+RL6AwoL/hD9/O0CAP0ECQz/CfYW+v4F+/oD+/QA/f8AAgP3/v8CAvcG/vkBBQEBBvgG8fH/BP0B8gAFBAL4BwMLAPgGC/0A/wYADP0K9P/89f/5//4IBPgCAfgGBvgEA/sACPgBBAHuBQP99wwEAAII9gP6Bw0Q+QD7Ag3+Av4CDfv4/wL/B/YCAQL5Av4C+v4CCQEH/AEGBAz0Afb2+wT98PwK/vwFAf8KBf4MD/sE7fUJAwbuBwgC//HyBgMOAv0BAvsJ8Af89vH8CfUF8P0BCPkDEA4a8QYFAvn//wD3A/oF+QYF7wQDBvr/9fYJAwEHEuoOCQH2/gf99wn7/fL29wIIAfcJBfv3CwT2CwoF+gD7Bfr2BPP4/AD1/QwIDAIFBP/+BQEABg74Afr2AQ71/fb1+gEEAfgE+wT2AAEGDfv+AgL4+wz9BQ31A/UD+wEGCAj6Bv8CAwUGCv76D/wAAQMB+wIA/Pv9/u4EDwwNCw0D+QIIA/wH//n/AQMD+QgBAAcC/gnxAf0B+AYABQD4BgX7CAL+DAAG8Pr07fsI9fEG/vz4/hAFDQDw+wn+CwD0EQoD+P0NEvX4+gH9BwkAC/0JA/b1Cf0G/gX9FvbnAgn8AQgKBPH4CgcJ8wP/B/sLCAH3C/4I7vv69vcKAQUI/Q/2DQD18foBBPkDBfT2/Pv+AgL9DvkA8Af1+gn8EPsOBQH8/gD67wkFAfoD+AL5AAj+/QL6/AsP9PoA+QcKAAL49vkBCBMCCgQA+QABBgwC8AQP/AUG/gYKAAT7DPAB/gQD+v4BAwH59QoC/wH6+P0H+QsK8/z6+PgAAAMJBwn/A/cMCQEEAf7//vv++vsA+v0FBgH5+/z//gMI/P7++gAC/Qb/AAQJDf8A"],
    ["object-in-eye","health","+Pj4CuwBDO7/7QD4BQb46Av8AwACBfX0/wAGEQkDBhMB9QDu/e4L/AL2+AkE7/UB7/cLAvj/7wgDAQT0FwEP9v0K7fQFAwvz/voHAfkD8/38+QH8/PwE9f8H9wL8Cvnq+v32DvsH/Qrx9gwCCfn8DQsEBfsABAD7/vYA9QEF++z9AAH6/fT/A/78CAMF/vgIBvj9CAQG+gT8BPr7Av71BQQB//QG8vz/A/kDCPb//PH7AQYG9gYJBf70+f4IAPsI/f0JAgr3+gIEAv0BAvr9AfgICAQH/v0GAwIH/f/4/AEACvUIAPj9Bf4A//kFAPoHA/4E/foHBv35AgkGAwb1AO4E8BL1DgXt+/L1B/8LFAUHBQT+/fr9DBP0BwX+AQsZEQED8/H0Evv/9wz7/gP1AvoB+PoIAAP/DP8CBRP2CfML/P0O8ggEAPX6Cf78+e4I8f4R9Pz7/fT+CvsG/Qn28wr6B/YGDfIIAQYD+P/1/BX8//36CwYF9/oD9voDAf//+fgA+A0A7wz9+g8EA/3++AP7AxD5A/8EAvsE/fwC9//++AD8DgP/Awf7AwAABAP5A/gKCvMFBP36+gf/CgELBvYCBwMI//v49wD5//39BfzwAP4DA/7+BvoI//z9/AAC///9CQAFBPv+AQP5Af71Bfv7/QX//gX//gYACf79+v33AfkW5gL19AP3/PQAAgv1BQf7BQED+gsC/AAW+vULBAQBAQj/+Ab+CgIKBgruBQj99wUDEe34AwL+Bf4O+AoJBgPw++sEAP4DFfny+wIBAAP2DQT9AwfuAPMEAu4EAfb5+gAC9gb1Cw/98/T++vgF9vL7+P0H8Pz8AwL4AgUFDP76C/kL/QUE+v0DCA0C/wH8AQUE+wH+CQsIDfv/9wMCAfoNC/v/9gz3+gMNCv0LBfwAAP8BBvnx/wEKAhL++QH9A/QA//cH9Qn9+Pj6AgoBCf0BBQIE/Ab//wH9BfvyAAT+/wkE/f4J+gAEBf34Ag0BAwD6/QcE9/EGCAsEAfcF"],
    ["injury-to-eye","health","7vnsCQD4Bfv5+fkI+f4M8wD7+gIGAwn6+/X+EgX6Bw4DBesB9fT0AAL88BT/9fEG7gIMAAQIDvII9QITEvwG/QEH+e/1CP8DCwcCEgQCCP0FBAn7Gf0MDv/48/D4Bvv5Dvn2BvwACAD59gkB+AIAEAASAgD+9/f99w0EBBH/DPP09v8BCP75BwYL/vn++/wBBwD0CAD+Afz8AAoB/wL1Avn9AAwB+fz99gYA/gL8AQH+DwX8/AYA+QcBA/cDAwD++/YI/P7+AQb8+vj3CgAEAfX9APv9+/0NAgYC+AEE+/wFBQQB/gb9+wINAAECB/sJ/wIJCQIH9/v8+QEADQX1/Pz++QQB/gnx+vcCCP0NCwQC/wMA9AEBAQXtBg3/B/8TBQP9/gLyGwYE8wsKCvntAfTy9Aj/8Ab2CgQDCBDyBP8DB/oB8P8AAQb1+wP5B/sEAPUM7PwB/+v9BPj7AhgB9goBBgn+BvsC/vUK//b9ARP9Aw34EPv6+wUC9/wJBQrzBQMH/wsC9RMAB//2+ff5AP75BQ//DgMHAv0MA/sH/QUC9wACAP8CBvkB/f3/AQL0//YICfUHDgH79/oFBAAGC//6BwwCBP/9+Pr2+wj/CfH3CPoBCf/4BvgJ+PQCBQEBAAX+Av4EAvv7AwH1Av79AwD8/f8ECwb7+gn7EgMA8gDxCPsH//YI6/v++QkJCRH6FQID/N0MB/0J+fkPDvz+BPf4+fr9BAj4B+/4//fzAwPoBQ36Evz+9CL9DfwM/xMHAAX+9PwQ/Pn8+/0H9g0EAgEBC/wACvv+//307P0KCv4LAfkBAAgABgD2BgT59gIT+wwH//8H+vr5/v7//f4K8wIBBPoEAAH9CwgFAAIE8AQDBPwI/AX5CAUGA/4EDP3+/vYG/QX6A/7+AfsCBfcCAAEICAH8DgUBBwP5CQH9Awb4AQL9Cvz8+/kE//gC+AMA//kJBQDz/P36A/X+Bfz5CwEGCQL//QMA8AYB/v0DCQgE//4C/fwAAvoH/QX/AQAK"],
    ["acute-glaucoma","health","+/b+B/gEDe0C6AABCwcG+QYHBvjtAQP9BO0JB//wDf8B/PQB5fLz+BjzDgn08vgD8vwJAxT4BPkPDfgHCv36GAUG9gIDDgAABgH5BgYFCf/7/gwC/AD6//r//vX8Dff7Bf/8AAP6/wb2+AEK+AwMEAgKBvgNCPL68QYE+/j6CPUHAQMGAvj4/AYD//8A9/oG+Aj9AQAB/AL+Eg0CCgL/BPn3AAkK/foC/vv5Cwf4A/oBBwb7+gIFA/z6AP8G+gsBCfoA9wD8B/sCBQH9Bv0M/P0ACfsC/foB9Qf9AQL+8P0CCQcD+v0F+//8/AgAAQACDAgHB/cBAgYIAAYG9gP3B/37+gz67RLuEPz8APcRCv0I+wz46AgKAQT7ARIG+vf/Av78AvEC+fv+9f8J9Pb57/kG/f8T/wj/DgAJ+QUBFRQCFvL//g7+APf1/gkAEAL4C/4F9f8R+fMB/f32Bwj+/hL68/8B/vwK/vr8DvsBBQ7+BAb5CQP/AgD9/AT/DP/yCvwBAAQH/wIHDv8DAADyAf8GAgX//PQKBAMFAAYJ/vIH9RAB/v0E/wMB9f4O//kD+w0KAwESBf768PcFAwEACPoE+wIJAgYDAwEC8gH5DQH++wP/Aff4+/8O+QX7/fgE/goCBQH4/f/+CP37Cwf/DwD+Agj8BP4BAf//A/b9/AHiBfT+++oM7wLw8f/4CQkBCv3+Ce4HAv/8/woI/v4HChH0AgT9BwT/CPj/Dg399/rx+g77DQDz+gYM+gQP/xACCwP79fcDBQMB/w4HCgL39vkDAPcFBPn69/wA4wkECPkBAvb8AQIFBvn7BgLy//wXAgcC9vwHBfQCAAnxBQEQ+gAEAP4P/vsI/f37/gb59wP++/YXAQj6Af4EBQILBPQIAfUHBgj8/v0ACP4MB/v6/QgCAQP9AAj5+f/6CgX5Avv7+QQAB/gD+QII+AEG+wj++fsJEPz/AP/+Cvn9//b7+f0KAv74/gX7+PcBAAH/9f4EA/8DAAMEB/T8AwUBDvgM"],
    ["tick-bite","health","8PYDBvsLBvXw/gAH8/v88PL4/vYACAoCBPf4HgwE8goE9AH5BfQE/vsE/vEAAPgH7AIF8/YJAPkK/v3zAPUBAPUBGPoH/gQA7wfy9wz5/fgG+Qr2/gkB/v4BCRkV+fQFBALy+wD6/gQF/hH8AQb8Afv6Cf3/Bv0KBAv18gX6APr98wf3BvoDBgcMDgD8+voDAPgE/gT6Avv7BA4FBvzy/QP8/AQECAQUBvoMAfP+9vv9APoB/QkB9fkM+QYF9AEH/vf5AAL6BAIBBwD9CvT+/v4NCQsGAwkD/wEL9f0K//7/BP38/QX9/w4DCP//+wP//QH6+gMA/PwLAfkC/Qb8AuUI/xQF+g797v3/AO0F+/UA+Pj7A//+APv8ABkA8gsKBPQN+fbw+/zy/vkG8wL7Fu4N/e77/Qf8A/n1A/r7CgEJ/g34DAkW/wH58wMBBvwAAfcD+AX/BPL+AAEJBPr+DAgA9PcDCgEGFQkFBfwH+wL4+fcG+fsABfgK/v8D+//7BvsH/QH+Ef0F/gcJCQP3+wr2//7+APsEAPoCAQgE+QAEAgYC//0GDwH8/vv3/Qf89v/6/AL/9//++gQI/P8FAfj69/oA7wX8/Qjw/AT5/QEJ//0K/gIIA/z5B/n8AgQCAfX2APr+Bgj/CfgICPb2AvQN/fkGCfoR8vwQAQUL+Pzo9fYE8PMFAvP1Bfrz8QD2Avz5//8ABfkP7AAJBgkBDQ4IBwL+6vX3++wC/vbw+AgDDvn2+gL+ABMKB/b8+/8ACPL+/RHtAvn1+PX++fPz/QIFB/75EAXpCPwA/fT79/cJAwcH8fr8CgXxAv3zA/0W9v8MAQYJ/v/5AQX38vv6BAUGAvkA/gcL+AEECgkNAwj6+wIK/wD/+PoCBv4H/vr6AAAD/wMAAQj3+QME+Q4F+QYCAwX8BQD9/gUG/gsICA//8gUAAgkA+P3+9/wB+fwA/QkE/wsGBgYFDv/6D/3/BP8CAQMH/gAHAgIKAQEA+gEFAQL6+AkEAwAC//kB//P6"],
    ["scorpion-sting","health","+vH4CQXzC/sMCAgCBgb06v8F+QT6BAr6+w34CfTrDQYQCgv18esC9vvh+vv4/vwGBfwG/vf09vL/BPcEA/cCAQP2BvYG/fnzCwEOCvv+AfkA7v0BDAEB6gP4+PwIDPP8CAMIBf71/vsK8wX7Ff38APT9Bfv+CvcE+gMA//z3BPr9CAD9C/z2/QkCAAn4EAkFAfoC/AP9AP31AP0DC/r99wUB/AAEBP8FBfgEBgH79ff8AQsD+hH6BgsAAP4CA/IGA/8HDAX9/QL+DP0ABP77+wMLBw0KA/oH/v8D9AD/AwYLD/kBBwD6+wAIB/398Qj+BP/+/QYC+v8L//kC/Qn9CPPwBQr49gH39QH8BwX8AwP+FfH9/fgDAgQAAgcO+AIHBfL08f/yA/cH+f348P/8BhXw9gLqDP7/DAv3BB3/9e77AvwEAP7w+/kD/vgAAPsKAe8E9gH8+fsD//kNCAYEBQj6AwAGAPYT+fkPCQf99gsKBQ0FCgH58AUD/fMC8QrtCwMC+AT/+fz39QgE9wIBBf7+AgT//Qf7APj4A/0F9w3/9gQHBv4RBfoK/PQGAQX5B/QAAO4KAAH/APzyBwADDQH++QrzAfgC+AH5B/sA/fv8DAH8BQQGAgEI9gj+BwMBCgD8/foBBAQCAgYCAPoBAQD8A/4J/fv2/gb3BAkB+vz17vkF9+UHCAz7/gH7BfbtBgv6A/cFEPf6Cf798fECBhcDFf326wL6+uoH/AMD+vkF+QQH9fz29QEJ9f0J/wL8Cfv88wjyAvMA+wb/BwD9+gD6CAMSDQDk//36+gwD9vsMAAP9BfYJ/ADuEfYB//YB8AIFDPsB+f0I+AT3APUD+wAF/PcHAPr9APz9Bf8QCAr39f8ICv76A/H/AwUH9/r8/wAC//8E/QEE7/sE+wP39gQCBQT5Dv0AAQP8APv//gYG+AcKA/wDAf0I+P8CAP32+AwDDQQB/gMICAn3/fsA/wQE/v8K//gBBgYKAgL0AfQB/wIDAAf+9gkC9f8AA/wA"],
    ["spider-bite","health","CPP5Dfn5C+r/BBHxA/j38Qj5BPn0Bhv6B/cIEv7xEAUC8wn7+vj18Qry+gj9AQIA+PsK6wn8AQUMC/0BBAj9DA37++wOBwH1APcFC/sOCfH+/voCAf4G9ggKAQYCAfcCCP76Bwj5BPvzAAkL/v8HDv8SBQT1Awf2+wQJ9//8Avr+/gcCD/389gH8+gf7/f/7+wAD/wYB/foEBQMEBAEH/g33DgQNAvgI//0KBwv4+/8DBwX9+wr3BvIC9f8QCgYHDPUR+AEH+/72BwICA/gEBgAGCQn8/f7+/vsEBwIJ+Aj7+gD5AQD69QIBAgkH/wr//wP9/P/9+gX8+gL9/AEEDfvq8w34+/zt9RQMAQTy/fAK/AT9EB0X7QL3BRH8/PUCDvwL/fX99+f99v8C/QsBEOn2AvED+vUF/Q76DAAC//4K+wL3Cwj9APENAQb6Cgf3CQX8AP0FBu/8/QsN+vz6AQQDAgT88wr69QL6AAYIAg4BCfwD+PwGA/oJ+v4J9Af9+/0AAA8H9/oHCAD9/P0K+/UGAPf+AP72EAACAP8B/Pn+/QIABf7+AQECAfn3+/0AAQQE/PkI/wD+DPIA+gP/Awb7AwH/AQD1/Az+/wEDBwACCQUDAwT7/P4IBfkDAgUJBfb/CQMI+/sDDQkC+PsNAAP7//oC+v0H/gHyCv76BAT68wMH/PIV+/kFAf0D/Av7+/8PAfMF8gr2/PsSA/nx/g7u/f8I8vn7/PP3AQn7+AUGBfz5+wHq9gIJ/A8Q//78Dfv9/xb2BgMA9//+AQcK8/v++gD5/gP+BQn5BA0CCvgA+wQE/v/3AuUCCfgO9gUO/QQDBAECCwMHAA79DvoB/P78AgEHBvoP/vH2BBAOBvULBPcFAQgL9AgHBQv69fsBDQgD+gT98QD3BAoD/Pf58/n8Awj9Dff/AgL4Av8ODQQL9QsF/gb5+gEK/v0F///z8QQCCwMGAQL/Cg0D/vQEAvwE/P8A+gL4/f0HAAj1/QkFAf37BAcA9QcB/QMCAP74"],
    ["lizard-bite","health","APX3FwPpDPMBCAUP+QbzAP/2DvT/+QL0/Oz7E/YE8/D8+uv6AwEQ+PoC8gjt/O8FHQD69BIN+gP0BQL/9+cBBv78/Pr8BPv6A/UCA/vy8/oDAwQCCwMECAruCwYI/gL7/AgN+vMH/Qn+AfoF+OsG+gsA/wX+9AP4+QIGCPwBDAQJ+PT/AwL5AAb7+RgFAAAE/gP9/QAC+AAH9f7+CgcL///7+gcEBQIA/gEH/gn7//oFA/z4Afr+APcAA/sCBPQFAgMF/wYG+f39DvoE+wT+AAQKAv0C/P39APsE9f0GAgIOAP78A/74+AMEBv4B/v8D/QH4C/8ABQAD9v/9BP39C+nt9wf26gXx8P78C/IEAvYS+gD+7ggK6gf68w0K/QT+9/b67wTwAOv87O8P9/b6BwT/Cu4R/f/1CAn9CQH7DfcG9ATzAgUBAgAD/An8AP/2APsADQIEDPwA+wD8+QH9Agv8/Aj+9xAE+fwGA/MG/QL9BQL+9AEHAuwJ9AIE/Av4A/34Dwv78fkIAf8GBAUCAvn+/gAFA/n+AwIB/xALBv4A9wQJAP3/BwUFBg36A/oN/AD68P0GAwEKAvoGBfr5Af0AAPr+//f3/A3wAQD9Cf4HCQkI/QYCAAMC+P4AAPgBCwH/BQ/8+/n9+AH7/gQHBf0DBQH6+v79/fwCBQQAAgLr8+sJ/OoDAwr7AgjzDgD5BPcLAfgQBPELBO0Z+PUK/fj5C/H67gbz8vPvBvv9/P0GAgHz+fXqA/ob9AIB9QcA+vsI8gr39/v6ARAK9f/99f/2AgcCAwf8APf/BAMSBvcFBQwJ/gT9BQD7/gH+/QP9AAkS//kBC/7z9/v5+gP5/QEG+AUG/Pb/Bf35DP4CC/7+/v4DAAX9AAIB+wMLBAX9CgQGBQQCAwkL+gECAQH8+vQAAPkAAAD9AvoH+gQGAwn5AhH8DQb5Av/9+AH/9wYABQsFBP8H+wL7BgX9AAT/CgsF/f4IAf319fkK9/v+CP76Bwf+/gwD/wz2/gcIAwUA"],
    ["sprain","health","6PP9Cvz6/wXr+/EPBfEA+v/9Bwjx/PcG/u8FExn9/QwQ8/v2/vMC+Qf88/8L+PkBAAYBBgkI/PwL9u3/EAEKBfP8Dv4H7wcB/QTyAvf05gL1+QX+Bgz49P/79/gECgbvCAb6AwX9/BEE+wMJDgT6CPkMCvv9BQkCABD/8Qn1CvIIBf0ICP/7AgQI/voA/P0MA/0A/Pv+9vT7BQP7Dfn7A/gCAQUHAQAC+gUF/P72+gED/Pb2+gcC/QX/AAT9/P74/Pb/+v8B9gIHB/v7BgAK+PwKCfwIAwYEAwL58QoE9wn+CAT7/QIC+/78CPwC+P7+BQAD+wUM/v8C/v72BgL7APD98wP0+vP08/wJ/wkDAO0JAAj57fz/CAH4/gAB+vnyAfb/+fr5AfYCABP9BvvwDvgDAAEF+/QGCPYABvT+8vYIAgD+/v75Bgb86/T98vr0A+X4+gT8BQkK+/4DBwcJ+QAI+QH49P77BxD9BQX7+v8J8wv+C+f07hkJ/QAA8gD+/vv8AQoB/gz+9wX4AwoGAgECAfv++woICQQCCgcA/P7/9v4FAgAI/gIQAgQFAPn99f8CBAb2+/z6BhD7+w73AwELAQAE/gYDBgL3EgQB+QEAAfn7AQkE8AAHA/70A/76+gP4+//88g39/w0JAfv+/vj/+gcIAv/yBfwHCPsFBQDq/PsOAfQB9fQH+Q0D6gYECAj+7vf/+QEC9QARCvUJ+wX2/PwI8v/6/AEGFPgFE//4CAT7Bv/xDAwA8/3f+QT+7/0C+fED7//4+xAB/+/9/vj9+/X3+/T3Avr96wwB/vwBAQYI/AP+DgEH7RH6/f0V9v3/BPID9gQFBPkE//z9+vkL+QP4Cgb//f/7AAz++v/2+/8K/A0H+gX5Cv0DAwAAAwAH9wEF+QIF+wAF+wn6AgX+AQEFAvz7/wUE/wP+BAj2//728AcHAgYGBfkG+PsDAggGA//6AQYH9v7zAQkA/gUIBf///v4DAP3+APn+/PwF9/v49wUNAv3w/AoCAAAG"],
    ["dislocation","health","5vr2If/0CPXuDgUGCwf2/gcGAf0C9AoKCPgPAe79//cF+QIGAPv5Eff5/hb78wX+/Pz7Bf74AgkHBukH9vH9B/f++/fvAPzx/Afr8QP7DPf+//v+BgDw+wwJC+z0Bg77Afrp/fgHBwMIAvkB/v/3BAP6BQUB//sNDwgD+fn+BQL09vz1BAEGBAH6/wQOC/4F9/8C/f0HCvv+/AH+/AcA/goABgMJCf4A/gP99/sD/PQDA/75Cvz6/wEA+/gBAfYDAPf//vgCBP4A+f3//PcB+wMI/fv+BQECBAT+8gUC/QAIAfr3/QcDCfz8AQ4D9ff5/wXxAwIC/QAH+vn+AggABucKBxAFAPL98AH/DgPx9PP+9QX++QT0Cg/9BhH/+fkVCg8F9vIE+RAGDAH0APL/CgUG8vwA+v0CEvvzDPAIAgb78f30/fv6BgMM7wPy7AYICv8B/fn6/v8JDQABBgoR+Q0HCv338goC+wX/BwAI+QH49/T5+wEC+/L7BP//AO/8A/gC9gD6BP0E+PD8/wP9AfwECP4FAP72CPoCDAf+A/P6Af8BBQH/CQEE+/n2+AkE+v8CAQn9+/z8AQ35+QH9AvH9//4EDAUD/Qb6Bvf+CAT1Af0D9f4JDAIGAgX9/fwG///6//sNCwj8+vgG//8EBwb29QEOAAED+/73Avn9/vryAvUE+/4D+vMQCfv99Pv4ARH8BPL4/gkD+gURAvgL+/r39/sN+vsH+QYNAwYI/gf18AP1Af8JAxAJ+f349vn4+fUDAfMH+fQLAhID9wMD8Ar2/fkCAvL6/Pzw/PoM/vb4DQL6Ef35DPP/9/769QgG+/z6/v37C/f/+eoO+f4C8woL8v39/w799v3/CAcM/gb6+gL+//cDAwL8AP4J/fgBAAL8/vEF/wX4Cwv7/w/78/v9/gP2+/MBBvcI+AD6CBD4CAX67gIC9gAKC/wBAfoC8Q4K+v//Bf4HAAD8B/v7+xAD/Qn4BPv/Av78AfwJ+wMB/QMAD/j6/AH+9PQCAQb7"],
    ["hip-fracture","health","9/79+gLrBgXw/PH9BfAF/fv8AgnoB/8B8u4EDgkIAgcGDvj2BPYD+AX2A/4E8/UJ+wgADwT9/f0F9/UIC/z1BAvzBf39+gABCg8ABAL1BAAAB//s+Pz1+wwACvYO/wX/BfvyDQMDDf37/wkdBggBAvwJEPT39gAY+QP67QX/Ae4GBfP7DwgDBfT9BPYHAvwH9wL6/P4H+/4HBwICAgcFBP4DAREHBwYDAQb/CQT+Af4N+fb8/QT9/P8GAwL6/QYJ/PkG+wIH/w8ABwD6/wADAfIKBA0D//7+AwwBA/kF8wH9BQYEAQQIAgT4CvwH+QQC+QX09AL/+fsK/wwA/AX5+fb9+wYL+Pvv4wQFGfL99QH3DhH3+Pv8Bf/5/v/97AgBDf317RL6+AMKBP/v/PgG9f4ECAIBCf4KHADyCAn9+fgC/wD0+/4DBvoMC/L1+/oJ9P//AAMD8gMEAQDzAvv6Bvn6CAoBA//98A0JCgwC+QEG/wrw8/0EAgMQBfYHAf4ABv4H+QoABfoAAg4BCfIP+wL7/Qj/A/cBAgEN/vkGAv3+/f/3Af8HAQUT+AAEAQP39vbwC//4BP7+BgL9BvsD/AL/A/8C/wj7Aw35DAUD/gIG/wAEBPf+A/v7//n8+/gD+vIB/f4C/gsC+Qv+B/oBBgH2/AAFBvoA//4HE/r7AQHu/fcK+foE9O8F+wQF6wL6+vMG+u0D+hf78vgL+vn8Bf34/OYH/Av98wcK+QQGA/4JBhP6+fgECgQFBgL5/fEAC/UABgAD9ggEDPHuA/UD/vwI//oFCfj++PUABAv8AgUCBfcFAfoK6AYDB/r8BQP+BPv+CBP5/vgEDf77AfoI+AMBA/0Z/w4D8vcaCAcB/gkCAAIL+/sD+AH+CQP9+PgAAfsABgUI+/0NCAEI//73BPj6/v0A+gX89gcNAf0EBAj4BQEGAAcJBAX9/wgA//8CBAUACf8CCPT9+/3++vr78P77/f/3Cvb+A/sKA/n6+/sB/vsIDQj47vcBAfv+APb7"],
    ["wrist-fracture","health","7QD0/wj0AwPr/AAJCfn59gMHCvPy8AABD/P7DQP4/wAB/f7/+vH+/vz4AAoF+fsN+/r+/gAG9fsMCPH9Af37/Pz+DwQG8vv6Cfj8BO3u9fMG9fkAAv7t8gf6+fH8EwTyAgH9BPn19RMIAvIEDPcCBPfyB+4FAPr6AvL18/L18vD9EfgEBgIAB/oA//8HAAEC/AMD//wAB/gF/wACBv0B/fYD+gUDBAH9A/4GBQUTAu76+QUE+/3++gT/D/8AB/wL/gQL+/kKB/8HCvgCAP74//wKBQQDBAQF/g8K9AYFAgsDD/3//P32BAD5BPoD/P0EAPsB+gUFB/oFBP4AAwD59PYE/QsN/gby+fwGCwr9AvYJBAju9vwHBAb5/wr+9QD89wn78Pv9BfoA/woUEQMCDfEECwQJAu4KEPv1+O7y+fEMAf8B8gP7+AUA8Pv+6/8AAOf3+fr09/8OBAX0EAcB9wMJ8gj/AgUHAAf+Bv4G/AD69AT7/e/29v0BA/r29v32Bwz+BgD//QL7AQD6DgYC+vUE/wAB+wj7/wgF/QME/wP89QIFAgsD/AQG+wgBCfoGAQcAAQn8+vn/AgsD9wz+/fgEBf37/Q38/Qj3CAMF/f4LB/MHBv8A/Qv8/O/zEfkCBQEC/wcD+AP8/AwLDAP4/vYAAQIFAhH+BvALAwf7AALm9f4I+e//5ugBBQEA+AbwDgYE+uT/AwwD9wISBPX7CPoB+Pb3+Rb5DfwHEAX66gj6/ArxCQHu/wz+8wPy+v/xBwL//PkAAfwGB/T/+PMA8wDmAP4M/gAA/Pz99A0MBgIHD/cB/Pz/B/MBAv/2Bf/3/wINBQTzAe4KCv8ABAD9+gML9ggG/v0C+f/+BgcH/AX3B/YAB/73+wEB/Af5/v359wAFCfz//wT9CQMBAgPy/Pv4/PcC+/n6B/4MAP4FAwT5/gP9AQD+Af4H9wwFAAP/9fz/B/kA//v6AAH6+vv7Av4A/Q3+BPgGA/z+DgX4/Pz8+AABCgL5/gL+BgD7BP7/"],
    ["rib-fracture","health","7fH5D/jmAQPl9OoIDwz0DAURDPv/BfoEAgT+D/b7/wMKBf8EBPP//RYH8P///PkIAfQFCwgD/vwK9/Pw+/z8/wn2EQL//PgGBP/jFwT77fwDBfUOBQf7/gUK//8D+AcJDgL1DQEFAgn9+QQCCAIAAvoJB/7r+goGBgD9Bvr7Cf3//wD7CvT3CP8E+P/6C/37+QL9AgX7AAMB/f8I/QkIBf0JCgAAAgv4//n3AQgC+gH3/Pb4AAUN/v/++QID///1Af4ABvz5+gL6AAD+AAMEAP8I/wEDA/8C9P72/foA+AD9AgH7CgMA/f4QAgr/Af36CAf9BQT39QMG9vgAAgf/BfYBBgsH7f706AQA+gkHA/YHBQsC8fv1+wP5CBAC8v8JBg4ABfkF/foH+v4FBvD5AwH++f8ID/n6Fw7o/AMC8gP6AQkL+f8A/Q8C/Qr29gAA7w78/f39+ev3AwfvEAcEBBMI8QED8fz99/gBBwoCDQf4/hb/9QMKAwME/+0DAw/yCAUF/Qz6AAEM/wb8AA39B/v4+wn9B/wFAfwE/gMH/gX4+f4AB/8EAwgIBQT7A/j//wTzB+8EEf7+/QkD/fkQ+Af/C/769/7/Awj2BvcGAgQACAIGAwQFA//5/fj5Bf8FAAIEB///BAD1+AQAAvb7/f39+wEBBAEEBPv+Bf4N+wL2/gALBfn1/u75+v4H/QcCDwEC+/0A9A8K9xD2AvsCBP77DPgI8/oBEP30B/n6/wvsDv0J+BjzCQEQ9vT+9AgGC/r+7gb3+PkB+f0F9/r8/vL5CRD0//sFCQIAAAcJA/34DfMG/gD4/wkG+wAD/AH0/v/+//QIBPL8/BD1+fgCBfz7CPML/QIA9P0BCP4F9QUHCP8ABQ/5+gb4C/79DAX+BP/7BQcDBwoDBwQJ/Qf9/vsD/Pj2CgQR/fr8CvsDCAEAAATv+PMD+AX38gP2BgMEDQP7Bv4JC/kN/QEHBf8FAQj+BREGCPn4Au4EDgL/AAcB/AQFAPQJCwL9/fkA/QDz"],
    ["open-fracture","health","8fb0CvD3+Pb7/woG//n79AsD+Pz8CRD88vf9CxX9DAoMAf0AAfb/8+7z+gztB/z1/BAL+P0L+QcL+QUF3fX/Afr/Bvv4BvUKBP0GB/j1Av4E/wb5AwAFBQQAAfgD8/f7Afr2//r9/QkFCBD++wDxAPwAAw4CCPD8CfcC/vwI/Pv7AfzyA/8EBfn0+v4MBQEMA/YE//r6+wUAAf4BAwP5AggC+/4E/wEF/v78+P0JBAP5BAP5AwT8/Pz5CfsKAPoM8vT4AvECBQEC/vT6COr7/f0J+v8IBwgM+v8EBQYB+//5/AEJ+///C/8GBQTnA/f9A/kFAgYB9An59wP9Dgn7CO4I/AoC7Pz26goBCP3wAwUJChP19/4GCwX19BL6Av0E+v/x6Qb89AkH//sBDhAXAQT2CfcFBf/5Agj69/35+PL1+wTy/QfxAfgJ8P4D8AYIBvT8BwgG9f8O+/7/CQcC/vYP/gkOB/0J/vkC+v37/AP+Cf0G9ff6/gUH8Pz19v7vAAkFAA/0CPv5+gYHAg0GCPwABAT6BgP+APwHAgj//gTv//kF/QcCCQMEBwf9AfsB9vz/+/EB+/cI/wICBvoHA/oC/vv5AgMF/AgCAQL9BQUFFQcDAgQCDQH2BPz8B/n6DQkC/PoIAAABAAP/CA7/Av0D/AkA9/77+/b9+P3+//L0APz+/f4A7v38AwML9Pz4BgUE8gIEBQUA9foTC/4E/fsB/AEB8gH2/PX+FgP8CAvxBQj9AQn3Ff7+/wLp8P8F9wH99OkI8AT9//4KCfIF/AH49vDv+P4OA/cK6wwAAPoBAfoJBQsFBQoEBAX1+vT7APT8DP4E9fsNBf4B///09fwM+gD8CP79+vwA9gv/9g0CBwANBvgC/fsBBvz3CPr+AfcBBQIT+QUGAfwEAAD3+/8OAf8FBf0AAPUBAwcA///79QP59/QJAQYFA//+8fn/Bgj5BQ4F/QoH9P759wv8/AH9AhIDAfoD+vsBC/wF7vD2+f/+A/kCCADy//kJ/PkC"],
    ["splinting","health","8QoODv0FAPr89wD9Dvj78AQHBPsEBvIFAff7DAX6AvwHCvoB9vwI+/L/+QUF/Aoa9wcG/QUD9Af//Pn89P32Bv35/+v7Av8D9//2EQrzCQ/1/gL8+fX6+wvuE/oECPcFAwr9AQ8P9gQMAwIFBgLxCAH88wgBCgL/+gHyBQT+8/39BgMBAw379/kE/PwKCfYFAQsHAQP6+wL0AgT7A/328vv7/wcBCP38Bgb3Dfz3/AIJB//9DP/79gT8Cf3+AvX0/v7+BfP2EPQEBwP5AgoB/Qn+9gkBAvsGCfL99foQ8gIC+v4KAQf8/QAFCQr/A/L5+QMG9wACBAD39AkCD/7zB+//BgYJ//n+/fvzBwH+Av3+AgkA9f3/Bv7v8wkF9gkL+wAAAAH+8gH7Cwj5/gcDAQMFDvQI//P6AwD+/fwF8AEB8wPrAwHt9/wJ8AD/AA8E+AMDAPUJ/hME9P8EEQf5/v4NCwMH9Ab5//4RCQr3+BMKBu/8//gECAYK9v4F9Qfv9/j//QcEAfTz/QP6AxQB/QUC+gL2Af8B+/4F/hD6/PkFAf4DBAAGAP/+BQ/3+ggO/fv5+/cF+QH+/Qz++An//e8D+wMB9wHz/PT8BQsAAwEHCwAO+fH6/PoD+v36Bfr1Cvj++gP4/BIKAAL97vYJ9wIJA/oHBPf+/fn+8Q36/QL0D/8K9vf38/YE/Qb/8gXu/ggL8fb+DAX69eUeA+4T9Q0K/PP69QXuBwULEP38Cg/+AQT4CP/uBhAC9gH6+gb/+P75/u/9/QnyC/UG9gD5/vbyBPf9/AL/FfUF8AAB/fz3Cwj+DwP2+gYOBA8JBwQH8fj9///6AP8FDAEE+wQDAvj//AYAAgP3+/wI9QMD9//+BP4BAfkM+gf7A/cDBP398gMFDQX5+/sDDwIBAf3/Afr/+PsB+vUACA4F+wME/foBAgH8/f0I/QEH/QEB/wcEAgIA/PQI/gEE9gH/AAP5AwAH//v0Dvr8AP8BAf/4+Pv9/v/1Bv8HAPb3BgEHBf0B"],
    ["appendicitis","health","8fn/AAHt/PriBPcBBPjt+fv+AAHoA/j+/f8DGAwDDgQIAuz6+/f4CQ377/QKAvQLBvsI//3++vIT/O/8Bgn9AgEDCf3//QILDwn+APb17fH4Af7+Cvv7CgP7AAb6AwEHBgT5CAb+BQjzBREA+wr+A/MGBQfzAwf7CQ8C+A36APgD+wkBCfr49QgI/gkE/PcC+wcL+wIG9vv7DQUIDQD2AfkEEA0FBfr/+/8HCv8C/AAM+gD5AQYCAQcH+wP98/j4Bf37AfwC+f0AEv4BAf0H+/X5CQX3+AUCAPTz9wUK+gL4Awb++wMFAAH/+gAD/f8CBP4EA/0A+Pv/AgX+BAkFCPnx9/X98v/66/nx9Pr6+fwFAwQE8f4A+QcIBggDBQMEDu77Cf4E8ggFAPsFDP30+gX2//n2BOn59xfv+AwOAf4NDAT6/QX3AAb8A/wD+/rx/f/4DwD7+wMF9vz6AP4L+wAL8v0F8vf8AQAK9+/+APz8+gIM9wID7hYCCe0JAAQE+vgH/RL//wEAAP8ICQH3APr9+gwDD/v/B/wIAAj/9AT//g0B/QD8BgHyCQn1DAD7Av/9BPkHCwUABv4K9u34/gP/AP79/Qn1Agv3Cf34CQ3z+/wL/PoK/gkDBgICCgHz/w37B/v3BPsC/v0DCPX7BP70BAP+AQcC/gAA/gIE/QL29PYIA/cDB/MA/vIB+ef1+w39AO/3/PYI/gMUAQ8I/QYC/fT+9ewODfH+AA787AIM+vn88gL4/gMFAfcOCfoA/w3+9/zyAP0W/wL++QDu6/YG+gf4/QMB/f8CCO8CAwUOAv8EBvT7APkCDvn09/z+8gYJDPkF9wQQ8hPv+/75+PwHBfoBAgH/AQL/DwUC/QP7AQsL9wf/AQIHCwb6+vwG/w0PBv/3/wP88AUHAQkG8Qr9Cfv/CAgD+wIFAQL+BQMD9woIAP/4+/0EAgMA/wX6+AMGBf8ACQIKBf8DBQkE/fj8Bf8FBQj+Af8E9wL7Bv4E+wIK+hAG9wEF/v79APn+"],
    ["acute-abdomen","health","+wHzCQ/3/ADvAf31/vPx/wYEAv77Avry/AsHDAwHBfz6BQL+A/HjBQr9BQEU/fkEC/L8+Qz3+QT69/kEDAQBBQgL/P/9/AAQDgkGCAQF8gEJCQEH/gbzAPn2CgcG/f7/Cvn6B/L1BAEE+AX0A/r0De//Dvn5BAMIBgwFBvT2BQsA//UABf/8Af4H9wMGBfv59woBBf4FAP0L+w0HBP4BBwYDGfr8+//4+Qn8AgUC+wIIBQPv+v0B9QIBBQoAAf4A+QAH/wH28/cECAT//gQPBfgADv0I+APtBAPxAPcA+fwA9AEFA/8IBgMA/gwE9wQE9Pz7CwL7B/X28vn+BPvsAer3+Afy9QUB7Qfv/QH5+Pb9Bv4O7gcE/vn8DRQB/ggAAQb39QL38AIB8vcFA//xBgj+A/z8B/L5FAX5Ahv9+gQD9Ab2AfT/BQ4O+gf+9/Tw9gn9//j9+vz4CP/18AgFBwX47RUHAwAN+gEL+AMBBwr6Bhf0AQX6AQP8/fv4C/73BAH8AQcG+wT8//kNA/sCBfsJBAb/Cfn5+wYOAQkRAAj+DwMHA/4IAQD/CAsBCf/2B/z89gACAfn++vwDAQL+BQb2EAD5+/P9/wT5Cv7/BPTzAwoBBAD7Cf8DBPwC/fL+AgkG/wMDB/8A+f8EBPsB/Qb3BQAG/AP3BP0M+QAFAgLuBP0N+/MH+fQDAhDy+vEI/QD1/u8E7wb1DAEH/wj+AAIQAvwLBvv+EAX5AAn7/PwD9Qz0CPf2///58wQFBP33/g0J9gIHAfv+GAkF9wH8+/AB/PwD+vkF8QEF5fkDA/4HBe4H/QECC/8BFfv4+fkR+f4O9v0L+fz0/wQJDPj3APvuBQQM9f33+AL9Av0B+/v5/gf9Agn89gL6//oF9gAEBfn/CAQEAAEEEAETBADz9hgDBv4JAfP6+/ECCAH8BAUP9gj7Bgf9BgYKAgX6/P4D+AEND/r9+f8B/vv5+f39/Pj8+f32BQUAAvv7BP4CBPr9+/8A/v/4//QC/gYHBvwC"],
    ["seizure","health","4QwADAnpBQ/6Bv8FBAT6/Pr9EAoHBgn4/gT/FvP+BP8O9BD6CQQECvIB+QEACP3/9AsHAPv8Ff8F8e8S/Ab99gYLEAH9AvkCAPUCBQH8EP8NA+0FBvkL8/sPCf4B+gv48hQHA/8F+wv7CAb9/wAB/wz7+Pb39fv+//nxC/wB9v0B+QQNCPYNAwX6Av0X+wMCAgUDAPH4Df8CAwUCAgEDAAX+BPwCCw0C/gTuAQgA+Pv8CgAMD/f8/wEIDPz5Cv4B+/kKAfr9Af0A/QX7BAQF+v3+//36AgIK/wAF/QT/BPkEAv4D+Pz59/b8AgIH/wD//fv6Bwb8/fv/+gECCAT89ur5BAr99QP6C/jwAAoCA/gBCQcB7wj0AAL7CxIGAwME/wQJAgXv+v7u/wD/BPLy+/YA6QkH+gj+Cgb1AQvzAfcMB/8D9/37+wwFBQIFBAgEAgEDAP8K+vf+A/X+/gX6/wYFDgH3/eEJAQv68vv1BQgDCBAABf78/QAA7/wGEv/4Avz99PsD/A/6/v0DAPnwB/3/AQ73Dfz6/f4DBwH7AAkABf7+BPr++goA/vf0/fX8+ez+BfgCFfb89wILFQUMA/z7/wMMBP0I/QMBCf35Cv/8//4IAggBBP0KBvAA+P4K/gX7/QAG/P38AAb5Dvn+Av76AgUAAgj8/gT8Awnv+PfqCwL6+/v/6wD88gb4//gJC/cI8P/+/QkL7gX++fsS+voI/xH2/fj6/Pr9/PvoCvEEBAUHDAMJBQgJCgr6//UECQoDC/j/AAsCBvUA/P76+vTz++38/AT7BvEBAQoC/wP/CQTx9QAGBAEICfsC/gr4C/8N9QH6BAPpAvj+CPIQ+fv2DgH6AwMHDPv++wkMAQTzAPsF+f77/vwCBO4BA/YB/AYCCv8BAQUEA/TwCvv6BAcC/QcB+P0E//z9+ggAAw4AFv8GBwn3/QEA/wP3BAQCAgX9+Q34A/f7BQMA/gQC+gP4B/X6+gcD/AIE/w8MAP78+vz7+/37/f3tCw0LAQAO"],
    ["asthma-attack","health","BgboD/7r+RYF2fwA/AcO+gf+BwYK/PH88QQJAP//4vcH9vcW+/0I/wYX8vv7AgELAv4BC/kF/fwHAgT8Bfj5/PL/AgENBgIJ+vrzBAIN6/79BPkD+wb4AwD9APoS///9CAkADAXxC/cE+QMA+gT++fv79Pj7CwwH/wr+CwH/APr9AvX4+QL4BfUAAfv8BP4F/gUBBQL5/QcC9PIG/AEOBP4DAv4CAAr+/f8D+AYK/foD+AECBAAJ//r6AwDz/gj3/vIA+P/6CPf39P4DAfsFDPsHAQECAAP9/gD3AfgB+gAA/PwECAf6/AgC+gr8B/74Cvn+DwMDBgD9/v0A/gQAC/b+AiL17vwNDPIKEgIGCRL1/fkKD/j7APP9EAL7Auz0BgQFBf0D/v4NDwIHAPz8A/D5/Af+DAQC9+797f/w/w7++P8FA+35/QH5AQ/6AfQI8PgOCe8E8/H7AQD3/f8P/gMAAwYMAxL9A/D3+Qb0+AgECQH2/QINA/YABf/7///6AQv7//0CBgwDDP4D+/4AAAYABg72AgH0+Pv9+woKCfgDDAUJAvwS/PT3Af4ABPYF//kACAb0+/7+AAAH/gEH+/v/BwD+/AEDAQUFBfUA/v4AAPoFAP3/AAAABvj4AvX//QEG+wr3/f/8AvoA/Pf5BAX7BwL8BvsCCwMH/PkB/wH3EgAN/+wFDf3v9/z+AgL2Agb+9/zw8vX29wYMBv3nAwIREwb5BQT4CgcIAfj//QoL9AUT9v8GBAXuB/oB+PwBAQLv/wf+BAX4/vYFBwb1//kPCvvwBvnvAf79Aw8E/wUHBQcEB/AM+xL7A/4KAfwB9PoF/QgL/wz6/f7+/QL5/gwE/PH7AAIE9AQD8wj29wQH8gr89wL/9Pr7/v/zAgMJAA8E+wUAAv/19/3+AAUC8vj++xT5A/kC//gHAPYJ/wIC9ggE+gQC9Pj0Awf5Afz6Agz09wH+AQECC/vx+/v9B/j7CQMFBPgA/v3+9/P9+P0J/gAH+wIC+Pv8/gj8BfoE"],
    ["low-blood-sugar","health","5vr9BffsBBEA/OcIAwT36/b7A/zpAfgLCA3zDv4HBQ30+g329/4R9/YFCAQC/gbsAAP89/r7AQIKB/0R/wMH9AoH+AATBfD89AH8+wMD/xDxAwP18AgA+gL+/wL+8fwFBfr0BQD0+wQC/Qr/7vcDBATvCQYE9QH1BAX+/wMBAPQB7/H5/QEI9/4CAP0IBwH+Bv0IDv8F/gIHAgb9/v4K/f3+BQD3+gP+/wIH+PsMBPMO/Pv59vsC9P/4BAX+Ag8G9gQB+v4LAvf9AwL//fwD/wIJAQcBB/oJ9AIB/gYFAP8DAff39v8F/AMB+/kH/AMJ//n3+f0ECPgQ+v8A/v0A+e7+6voA/Q0PAfwH+PEVBvME+wbw+g4F7woABwHvBgn8//kA+vIJAQ3vB/4JCRQI//z//uf9//z+Agj7FPIV/vT8/wD6AgwH8v8E8un6APoDAwAA+wv89gUD/voL9vf++AEL+AH/+fwC/u8A+fkJBwD29PoF9AUD/Qb1+vkABwbs+g0EBf4ABvoJ/AL+AgYCBPgG/AL9BAsCAfoDCgX5CfsM9gP9/gQQBfP2BPz/Bw0BBvwFBQj+AQAI/AT0Bf77+PMD/vv2A/79/f8FCAYD+gL6Awf/AgACAv8O/wP7BgT6+PoN8/77/wYFCfwPB/r+/QP//QoD/fv8+/70BPwEBAXl/PT/APkBCQvx6AT8+Pvy+vgR6gf+//P2DvsHAPLz8ATvAPHxAQYL//0CBwQG7QP4BgPuBwkBBwgABQn3EP39/vMBAv//AQMA8gHr/wj+EwAC//QD/f/yBgr59gYF/vwCBf8HAvkI6/cBBAjvBgQHAgjvEAD++v32CAUIDg7+BQ34APf+/f3+Bf35Bff7AgQFA/kE/gv0CPr5EAAEBQb+Bfv4AAP5AP8A9wL6+QX6/fr+BgP4Afv4AvsI/QEB8AP89QX8AvcD/gQS+gUE/QgI+ff8CQQB/vv5+AH++/4KAgf9+vj8/v0EAgIBC/UC+QAA+v0B+gQA8QD2AwMABfr/"],
    ["pneumonia","health","8/r2CvjoAAr6/O7z8g4I+PoD/Pz4B/r//QAUBfn57wUMBwQOEgb5AQMJ8ewLAOr67wj4Bf8M9/wH//UADQQGAwD0AwEF8wYA/gH+CvwL7fnzAwT/+gEB5gsFCP0OAQP8CA/tCQj9BgX89wX4/f39+/7+CfT4AQb5AwMOBQUF/P8LAP0DBQ/1DvYL8wQDAvX9+v4AD/7+/AD3+gYIBAkEAgT9B/38CAgDAvcB//4R8PME+vUL+Q0M+vgB+wQC+woE/wAJ+vz8/v/7BQb9BvgF+/8JCgQD/vsD+ggFAAL+A/0DCwMAB/8CCAII+gID/wP+//4GAwQIAwIE//wGAwX9A//3/Pny4wAC9QL2CQkZ//4FDQARBgP1AwX6DvPx9foECP0JBhD48gsRBun2E/73A/IDBwMACP78AwPz+fr4Cgr7+RAA8ADy+wX9CAwCBvT98/oCEAAC8/wKBQ35E/sC+wcN9QYJBgEEA/wL/v4FAvrzBAUF7AsM+hABBAj5AQn/CAAH+f/49wf6CvD7+QX6CvwC+wEEDQYA+fABCAYCBA0K/An5/An6+/4AAQEACvz7AfsEAQYKC//8AAcE/fcKAwAABv4C9QEA/QEK/wgG/wD7AwsA/woFAQj8Afz6Bf4FAvcE/QMB/Pn++vkEBwT6+wT+AQIJBgIE/Aj9CgMG/gD7+fcG+OT7/wLz7AT1Gfn4/Af3+f8H+/sGAwgK8u/sCRP0Dgf9AfgB9Qn49gQD/AHw+/gGABMA/fgA8wMLBQIG9PcD/f70BgLx8vID/wDx7/oC+/8BDgD5Bff9CRXx+foGBfAC//4A+gTvAfoA+vz6+QT79vj/CvYK/xH+/P0BB/78BP/9/vQM9Q78/wAH8fcAAv4JBAPzBvXyBQD+BgD/BPwEAwEFAvkE/Pj/+Qz5/vsGAwP/AAX39v/2Avru/v8LDAf8/f8G+vsGCgYG/AkHDv4IBQIKAQD8BAEEAf4C+AP8+QAAA/sKAf74CP/99/sCAQEL/AIEAP0G7wP8BAMD"],
    ["meningitis","health","+PT6CP7mCvfzDP4D6QsI+vYAB/zs/AX+Af4DFe74AfoK9/8QCQ3s/ukE+RL6Bfzx/wX4/wgIAfwK9/X79v4D/QXxAgr//f8H+PQIEAcECu0M/PgA/wMJ6vz2AvII9QP9+gb2/wQI/Q32Bf0M/Qf2+f8ABPP29gv/8/f1CQAF9/0O/wEH/wEECwEJ9/oHAPv0BP8H/v/5/AP9AAIJ+wgB8gj5Af/6BAf+AArx+AgG9gP9CAMDBgv9+Pz8Avz8/P8MAQAA9f8C/wAF/Qz9AgEHAP0BBQH+/Pz/BA4DAwj9/vAHBPX+//gBAf8D+wEGCQEN8/4DBgP/AwEA/vr+APf1Aejx/P3u9AD28PH8+/z/FO8D+BEE+QUU+/vrBAT5AfsCCv7w7vj//wAL7/8K/uT8De4KA/cH/g4DCfUC+wYA/gkH/AoBBgP79vj7CAgH+/IC/AACCgP5BxAEAf0D/A77/RD88AYBCfT/+P8N+fYDART9DAf5BAX///YHAfwH9/r1+v0LAwf0//4F/fMNAQUEDQEEAQMFCvXw/wP/C/v++v/3/QP9/gADAv0CBf///v78/gEH9/z+AAT/+AP7DAAACfr0/gIE9PoA/AHy+wr4BP7zBPz9/v4AAAD6//8B9wL2/QUBCgIB+/4ABP0O/Az6Bf0FAPr//P3/9vQB+wAA9gfk8f3+/fYEBPT38v/1/Q/19wjvBesB7usA9BUT9xMC/AwGFQAG/wMF+P0D/v/vAQD4Cv4L/QD08/74/gD5CxMKB/EDAwL6BPoIA/v5Bf7/BfwEAAIJCQX5AvcF/A/0+f///vH2EQX8A/b8/An8+f0LAQUD//v69gID7QkEAe/8Bg/5CfgADfkGCQH4/gT9+Qf6Awj+A/4E+vL5AQEG/PP3/QAB/gcAAPkC/fn79AIC9gMH/QL9BwQB+v4JAwb3+gn/+gwD//4CAAr+CQQA/ggA+QMJBgkE/wb++Pv/DAjzBvsIAQYGBvn3BgH++AAC/PsDBQb7Awz/AQX7Bf4CAvH2"],
    ["shock","health","/vvwEwX2AwD89vv+BQ0M9/EA+wgB+RD1DgfyD/r3DQr9/wb5BfP//fH2CQAO7gL0//sF+wQE+/7/+fsB/gD4BwT/BQD3AAv8BPz3AQDz6v0K7f34+ewBAPr/B/sFAwLw9QHtAQUP/gj8+g3x8vb69hP1AAT69vcACgULAPv9+OgACQH3C/gJ/Aj+BvcPEfz67goGBAAJ/voQ/gT/+QQAAAj6+P0AAPwF/AEF/wUFAf38AAUA/fz+9gX2DgwJ/wMC/QYP/v/9+fcACAABAAH4Awb9CAECAgH5BfkF9f77/wMG/wX+9/72BgcGAfz19Pf+/f7+/wj8EAQC+fYDCwb++/b89/337Ab0Af3xCAMDC/38/gPx+Av+EPv8E/oL6u8G/v0PAwoKAgH0/Oz7APT3AvD39usJ9g/4AAn6Ff4IB/76+ff7EP0A9O8D9QAC+wIE9gb3/fn6BfoIAgL0Bvv9AP4E/AYA+QYE8wIQAQH2+wIHA/0RBf4I+/zvBwz7/+74CQEB/ggOEQIGBwQA/wv2BPj6+Q8CCPsD/AED/Qj/+wQK+PwDBAcLCgT3Agj+AgIB/QAL/gP8/f4DDgUJBAH2Bf77CP7+Af8BCgP1BAUJ9g4J+QcNEP0G7wAG+AL3/vb4/gP//wD2Afv7BAf5AAT//QYD9fv++wj/BPgABP/8/gT4APb/9fYL9gj1AQL1Agzt7gQIAwQJAg/y9gT5BPwOEAEBDgoCDgH+8AH1CwHz9wHq+Av29voK/BQFCfrw9ggJ8/8MAwPz9vsA8f4GAOz9+QH/A/b9/fb9BAIL+wEA8/X9BP0HAvr8C/wFDPn6+PT7Af/4/Aj8BPMJ8P8F/BD2/REUAgIHDgb9BPwCAgoNBAQAAQoCA/r+/vP7/AMGAvgDDfj/+v8LB/4A/P4OCQgA//sD+vv//P8JCgILAAUF/Qf5+f8B9QkA/gYE9AEM/PYFBAkDAQYDAwQBA/3/7fbz+f4J+PwE/AL9/vj7/f0A/Qn+/Qv8BwEG//71AfQKBQH9"],
    ["tension-pneumothorax","health","7gMCCgXp/gT1+fYJCgn+Awr9B/7/AvcN+AUF/Pf89v0G/wgDEPgEBxQF9f79BfkG/RUMCvkH8AT7Avzw8AAKDP79AQAA/v4B+PzxBf0K8gXyBwES+QH48A0WGP0L/gsIBw35BQf5CwoBBf/99QT78vcI+vj0FAv8+PsADPv+9v0G/gX0/wAAAwAK/f0ABv0HBwb6BP8O+AUB9gkLAQkO+vwLBvn8D/j+BwD6AP4E9wPu9/0JAgEE+vX3BP70/wP+/voE8/r2B/L6+gEMAP0HBgsG/wMBAgD7Avn/APcFBAMJ9/8ABv8B/fwA+wb+/wH7AvYACQMJBAD3/PkF/wD6CPUE/Qz73vv49fX3AgcB+PsCCgUB+gj/CP8LCgb49vL+Bfn2/Aj++f4MAvL7/QL6A/74FAcLCfj4+AL+8f0CBAP6/wL0Af//+f/68gsFCeoC8AQCCP4F/AcUAgUJC/QEAv396A0N+gr89fUOA/gFAAH1EQT6+wUF/Q4KFP0H+wT+CAIF/Qf+8QP59/gECgj++wQABf0BCvQK8f0KDP8CCAP2+wYH9f0DAwME/QgDDPUB9vz9/P4DBvz9/voABPYCA/8K/f0G+PwDAwr3/P35DQcJDRIJ+gv89gD7+gf7/wIJ/gX8AQQH+QD7APwO+wL7AAEE/gsEAPcBAPr+BQMPBQbr//EMBe0MBvX39/wHEfkGDgMGAwL99A8FBgz/8/z2Awj3AQIH+woECA32/fv//gP3AAoF9Qjw9QUKCAH5+AUDCAAN/AEF+vn/++0FBQLn/fP6/RT3BvH6B/8L9gj6EgAECPL/B/X+APb9CPjz9hH8BAr8/fIQD/z99wT7/f8HCAb9BvkCBfoG+AEF+AEK+wYACPYLCAb0AAT2AAkCCgkLAAMCBPsKBAMQBvwFBgX09Pfz/AIBAwAB7/0OB+/8BfoD+vzz/vID/wH7Bv0C/QUFDgEMDAcHBAP+//v//gj+DP8F/wUBBv8CAv0DCPP//gL+/QQJBQH9A/z+/gQBDPsG"],
    ["dangerous-wounds","health","9wUQDvD67/cHA/r9EfLxDfUG9wMEAAT//AUH/hP/9AT/Bvf2CRMNDhED+vMK+g3qBf0K/fwA/PcBCgQIAfb+BAf4BegADAL5FQAD//v3+P4RBv0H/PkDBvgNBfn9Be8MAAUBBQUE/+4D9gr99QL6/QYA+vj+CQHy/PkHBgMF+QT+CAAA/AgF9+/9BxEE+AMI9wMGCQUG8QkCAxQC+wf69AcL//z/+P8K+v76B/YEA/vz9v4AAPcDBgMB+v0K+wIDBv789wH+/PsABQD8CAL8/wQABP4D+PoNAf3/AAD6BPgGCfb7CAcGAAf4AQAABfQC/AcF6/kC/wP2Av8H+wYHCuD0CQ/87vjzAvwC/Qz3AAMXBQIMABEK+gL7AgAHBfsCCgQC+wwJ+voG4/z/+v8O9vj7EQAA/vb6BRET8wEF7/wD/wDvBRD9+QUC/fYAA/oT//UFAgb5BgIG+/4D+wD/+//+8v8DBf0M9/kO+fwC+AYMBwICAAP5/wP5+vv7/f7/9wv/9/X88/j9/AT+CAsIAAIECwgAB/4D9gr//AQFAP/+APwD+fgEDvkPBwD9+P8C+PgD7/YHAPsH/f/0CfcEC/8C9QD3BgMGCAP7BP70BQIDGQMB/QIDCf8BAwr//PkHBwj5+gH0+QL9/QMC+gsAA/UC9QoDBvn5/fQC9/8FAvvm/QkL9+H48AIP/v0GAPoVFAkFC/oJCPwMBv76EP78+QoB/fAVD/wL/+79BPsDBPv6+w/8DgME9g4VCvkF+PABCAcE9vYE/fX8+wX+AfIBBf/yAgAG8wcEB/ALA/IFAgADCAP7BwMD/wUDB/T2CfsCBAb8Avv98/8D/PgE/f76C/0GB//4+AD29/QBAgIED/v+/QwBAgH1/gMFCAIKDQP9+vsEBPkAAAcGCAb8AgX9/QL4+/X6/ggOAwEBCAb8+AQL/v/4+AL7+wUI+QT3+gEGAQoEB/sD+RX+/gUAAfoBAAX++AD3B/8F/wf9AP0E9P72BvP+BAcD+vX8A/kC/RED"],
    ["wound-infection","health","+PQHA/T1BPwG9fr7BPr09gkM//7+8w79APoK/wb8CgIB9PXyEgntART4DAb4AQT4+/QU/gEBBfj7DQ32/Bj9CwD97/sBBAr0CQfxCQr/Av4LBvT5A/4D/fgFBAMMCPcCAPzxDQMK8Q3r/QP4+wsL9wAL+wn7Gf0AAQwC/f/7/PgK/wICDAT5AP/4Agj1Ef77AwUE/QIGAwn0/fsEDA38+QTyCQQAAf7//QMJ/gEE/gT8Awb++gcH9//7CgUJ/hEMCA0H/P0H+/3/APb7AgAJBPgCAgkKAfkE/Qj9B//3/PsA/AL7//MG/QXt+AT8AfwCCQz9/f0C+QL9Bf739v8CA/f/CQXz6vPxAvoL/goH+vcKBgD1/PwU8woABfwQ+gQC/vP68gL96/cI6Pzw9vMIAPjtA/0FCgnx+goIBgIL+wn9CO3zBwoB9/T5/f0B+v/39/gB/gv7/v0P/v77/Azq/woG/Q36Ff74/gQBAAcB+/kGEAYDAAj++w4M9v/1/w77BAT9BAz7/Pf3+gwB+AgG/wADAfkA/AD5+AIFAQcEDP0C9f0BAv31Af76BAD9/vUFBvUL+/8CBQkC//cEFP0KDQkA///6BgMFCAv1A/f/AwT8DQAEAQf7BvkC/AwFAP3+/wf49AH5BAME//sA/gMBAwgK+gT//fgFBfsEBf0GAwbq9QYF9d8B/foG9wAEAvf6DAgL//oDAP///QUOB/v6B/r69vQEBQL6D/L1A/wG/AAA9A3y/P4A8goTAfgNCPX17/8C7Q0C+f76C/78EvT8Bfn6DAIABgQACQb/AAcF/wn0//QOAgcTAP/uEP3/Df0J+hMK/f7++AIEA/3wCP0F9P4IBv8N/AD+8vgA/QUMBgoCCgX//AT0+PcEAAT7+/0B+QMEA/gEAwb8Dv8D+fv//gT99PfzDAb7/wT/Bfz6BgoBAf7x/QH7Cv0K9v8A+gX9+A8GEfgB/gz9BgP6/f4AAP8IBvv+AwX8/wUEBvz/A///B/AGAgf1+wL//Qb4CwD5"],
    ["small-wounds","health","9vcGCfXx9wwA+v34D/L88wsBCxX5Cwnz/v4BCgQA8yERBQPvAwsJ9vjt+QT7/Av8+P7++vMA8/0RCwIFBgX0A/77+PMOBv349/75A//99gX69BAK8QUK9wcEBA36AfwG/vP9//v59v8L+Qj7+wT/CPL/B/3/BAL8+AAF7/II/vjzCgIA/P8I9/v5/PwM/xEDCgEGB/0B+fkA9vkHC/rv+QMI/wwDAP4AAPz4//n+AwAC/P0AAv4ABwP+BPkH+/gF/fkGBPkH+v/4BPL6CfsL9vcRAwcIAQYQ+wIRBQP8AAP/BQD7/v8EBgX3BgP///cBBQT6AfoGBQX+Agn8BAX8/Pb7Awr69gL18wP+8Ar1Df8GBQH+7vgA/wn0DA8C+ez8/xDv9AMH/vgC//wA+e4JEPrzCvEF/fwL/wMVAfUDBwYG+QXvAf7+/PsJ9f8ECvz1AxAD/gb2DA4J8/IEBPz4BAD89vX99gL6AQkJ+vkFCwH6BwYLARsG/wIHCQj+/PoL+ggJBQT2Cv8IBAgLBQX9/gj5BwQEAP0B+/cIA/oP+v8B+gIABAEMCQb0BQv0/fsB/QT6/gQN/AX6FfkIDwL8+gEJAfoJAgf38/r69wj+BwMGBAP8+wEH////AAMHBv38Aw4B+QgECgP+9AL4+AH/AQoJ9/bw/vb7AwD5/f4JBQHsAAgC5AnqB/kADwASAfv59/H7AwQLBuz/DQIDD/T7DAX3Aef1BAX2Avv6Dgz6+v337gkCAO4EA/r//gQGAPz3AvsA+QcB/AD6AvMG/gHzAv3+/w72+AgCBf4ACPPv+AXz//ED+QUABQwG9PsMDPgG/f8A/vb7BQEBAQP7BQMODQD/9AAI9P31BO0DBf0GAw4L8gUL/wAB/f76+//6//n89Rf4Bvv8AfAMBv4E+/kDCQgMA/n/+QMIAvv1+wX7/gj7APwDA/b59QUC+/r7CwUE+gX6/v0FAQn6AQT8+Ab+AAL89wT5+wkJ+wEBAwD6+//6//f98voEBPr6AwUKCAQB"],
    ["large-cuts","health","AAEDDP0T+u38/QD6Cu73+/kHBP4H/AAG/wL3DQr5//4C/PrvBwn7ARQM+AP++/QF+PEQ+h747gX4+wX+/QIABQYH9u7+DPkD8gj59AT78/3/C/YACgUEC/YEAPb6/gQHBA4HBwMB+AYSBfn9B/UDCfsABe75Cu4BAAYHCfMLDQEBAvr9/gL2CQIG/QIPB/cBBQX5BAgN/fr9Bv//+v3/9gb8AvIBBQAJAwP5Awb9+f8BB/z6AAb6AAMD+fUMAP4C+Qn4Bfr9//cIA/n3//YEAwkNBAoE9fwOBvv8Af/4AvsMCvX4Bv4RAgDy+wkEAQIIAAgB7gX/Cvn4B/0B+gL+9P4BAAb99PHt+voH+gjw+e4RGRL9/xXyAw7t+hUD+/cACQH8+wQB9/cU7QMCBPr9DPrw/fgK/vsD/hYI+wX9+f/2AADw9Qn8+gH48foD9PMD/P75+AwEAQb/9/8F9wcGBP4G8gYKCQAC//sD//3+AvoDBw0I/PkC+wwO/vb5A/3+Cfr+/gMD9/8CAP8GBg37CQsC/QYCDwAHAgQABQIL9gr1+/0F+wL3//oOCAUGAv/58///8/r7DwcAAfX7Bfj4BgkE+voC/AEBBgz2//v9CAYGDv76AQn6AQL6//32/fgJAgcFAwP//gf5+gII/f729AEN9QMCAAH7AgEE8QgDBAD4AAMK8/AF+QLw9f4C/gIS/gkF+gcK+gHv/QP9B/0I/fb9Cf0HB/4MBQX1+gMBEv0I+/32BwDxAgoECAn1//gS+wT95Pv9/v4CB/MI+P3u/Pj+CBUJD/0TAwgFBADs/gD19QMCAgb49fr2CfcB/wgF+QUH9wUJ/ez38woDAgD3Bf76/AH8+wMFAPv6Dw8EAQT2AvkPBAX9Ag8R+vj8/wX9Bwn9+/79BgP++voJCQMK/+8JAv4HAP8G/PwH/QP8/P/5/QH//P4G8QIKA///9AINBgIFCwX/+gsA/g36Bv369/gG+v7+/QYK/vL+Bf4G7wL7BQkACAIE8PjwAAj/+/8C"],
    ["dressings","health","+P3+Cvv85f37+vkBDPj27xcPBvX0FAsBBu7uBwj4/AIIAP/+BgL07hX1+wAJ+fb59fn+AgUA7/P/DgLz/wDz/PP9+PADBgD7/Qbt/AT+8AcKBPkOBwkDBhL6/wXv/wQG/Qb9ChAB/Pz89/gDCvwCDAUJ/vj4APQQCgP9/PwABfn7APz4DAX5/Pj6BQz9DAIAB/8DAQIJ9AEC/wD+Bgz//vv7AAMG/AD7Av0G//77/Q35/f/1+PsL9wQH+/sN8Pz//QTz+fwBBQMABvj8+wICAgQG+wT8AP0HCvcPBvn89QwGBgz3Bf0FA/3+/P//+gH7BQr4/gn8AwEC/QP9CQ8FAe4GDAj0/fQJ+Qb9/fv9AfoRDgAM8P36BAkPAP0TAwD9BAP77wsdBgP78ADy/gMH7fv8Afb6AwP49xAO/gMP5/73/QP4Dv4J/Qb+CAIA/wgOCfABDgD7DfoI+fwT+Pjw/wXx/AAGDQX5/P4F+v0C9goB+vL3BggHDgL+/hAHBP4A9hP59/MABPgBDwMD+/oIBQEFBgICAPoCAgkC/g/3A//9+AQK+P4HAwcFAQT+CQEDBfX7/Pv9/QMDAv38DvIE+gT8//oBAgMAAwUDAfUDAAn+AQQNAfv+BAD+CgP+9wIDAAL9Avv/+wADAf4CAv7rBPoD+v79BggE+/kO+gYAEPv2CAYL7fjb+vz8BPUQ8fP2DgYF+vkJ+wQF+fAM/vX8AAoEB/kABvb0FAX1//v06QoCAP8HC/cD7/gBBv/+/fwJ8/zz7wL8+Ar2B+z+/P8BBQ4JAwgR9wMBBfX6//MFARAB/Qj5BQPv9wsJ+foOCgD9CP/6A/YJ8Q36+v4B/AMJCwkD+fwA+AMCAQIBBgILAAUJ/AT2Agb0DAEEAfb7Cvr49wb+BwP+/QIBAQIBA/gDAwMD/wb+Dgb+BAkC+gb/+wAGC/0M+wT/8/v8+/sACQj8AwL5+/v//xMH9QT9+P74Bg4CB/kBCgP/Bf4BAv4A/AcEAwL7/wT///P0BAX+Bv/7"],
    ["impaled-object","health","8QP/GQL8AvX9CQoLCwIDAAUFC/v2+Q/6Au/8CgrvBQUJ7/b0/gICBvD3Bfz2EPf8+wkF+QT9A/4S/ucQ/vj48P757/v/8fsF/AX+CwTzFwD5AgoBCAcEAgf+Bv0KAwADAAAMAAb+CPgQAhP7Av/vA/wC+Qr/AvgC/gwA/wIDCfQI/gwBAfwJ/PP9DAIHAv8AAe8B9PT8/AP+/Aj2CwH1AgT5+PoRAwQLAAMJBPb+Bf/0BAL68wEABfb6BgkBBPwH/wr///r8B/P9//j/AfYA/QX/Bgb5A/cG+vcGBAQDAvIMBgIHAQX9AwD/AwLu9v0EBQEL/wcL+AX/APkFDwAB/vD1/AX25u3x+fYNAff8+/kPCBL//xML+//y+/kI/f8JDQIB8APzCPb+6PkE/wX0BwP4CPv48gX7DhEH9Pv59wL2Bv/y9QH98gH/8/7y8v0MBPsK9gsAAQkICQIJBQL7+QIF/QX8/QX9AQUL+/oD+hEGBAII//b1/wcKAPr+AfjzAAUCAgL9/AH49/4DDREJDQf9Cwb5FPz7AAUDCgkF/AP6+vgL+vcDB/kFAwD6BAEE+wIL8/sCAf37AAT4B/n+Bfz//AUC+/f8AwntAwP0CwH4Cf76+QUABfT//w0G/fcAAfv9/f8BAQr8AAEI/gj6BP8KBQMIAvj4+/IA+QYLAP/9C+8LBgP8BfMCCgj+8wINB/359gMPDf4PFvcI/gz7Dw/1AP0IAPoJDP7/DfgAAgYF+hj6CwH79gn9BATyCgD5//UE+wP6/v0FCPMF6P7+AwT/+v//9QIO9vT8/QEHAgIE+vYT/gkA+AEM/AH15gT9DgUOAvD//u/8BP74EPwGA/r0AQT5/Pj8BgHzBAARBgICCAQJAQD4ARL5B/0EB/4MCAX//wX8BAL+7wj/+Q7/7vr+/wb+EfoD/P0K/wUG/AP9+gABBvf7AAUG9gEFC/oE/QUH+AD6CfkE///2BgMHAA0P/wcF+Pv+Bvz2//3/8gb/B/wD//sJA/8EA/7/AAj6"],
    ["penetrating-wound","health","9wD3DP3f+/DvB/33BQLx+f0WDP4A+wH1Egv8F/zvAQAC+vX2C/j5ARD77gwICgb/+Pn17wr9BAT2A/0G+/36C/cBCO32/QP7BgEABvr77fz2+/YPAQIBEPT+APv7+/0IAAL/BPv+CfXy+QkA9/36BQYSAf/6AgHz/QAB+PQA9/36/AP98/0B+voCAwcLDPz0+P0CDAcL8QALBQv+/wcH/AQNBAP99v//+PXzA/wLBAfzA/z9//n3+gcKDQMJ/gABAfsIAwb8/PP/AwgBCQMMDgMBAf0G+/8ACAH4/QUKBPgEA//8AAMJ/gf8BAEK//n+/AQA/gb2/fsA+f0HAfUA/+kA/gv7+fvvBfwR9gv79AECERj6AhMF+g4L+QYC9/oAAPr49RMICPsP+vL3Af0A+gX6CgD++ff0AxIIAQIE/AAB+wvz7wnt/QkI9vUB6fUP/QT2Cv79/gkDA//3AAQABP4FBAf7+v768QQD9wUGCAgHDwv89Aj19AX4Avz59AACAvkD/P4BAPkF+AcMCP8EA/36/wH/DfIC/AYLAgENBvf5A/YB+/36Af8H/v8CBv0C8/759PMB/QH5BQ35EfUCCwMG+/3+/v/2BgT0BP79DP4BCgb7BQACDQoD/wUCBwb/+wgA/v4FAgMDAf3+/PwAB+8J/fwEAPL1APX7Agn//wvz8vgF/ez3+eAGCP8QBwECBhQBA/gBA/4RBgMLAfn6/Qr0/PkG//sSDfb6CwIH7gj+Dg4AAAvvAwEF+fj88vkP/vv3AO33//0ECOwD8gLs+vv/+w4F8AUCBP4C9fX/CQoI+PoUCv4JA/IBC/P4/v35AhABCPICAPoB/QX1APUIAgP+Afj5Afb5///7DQUT/gP+BggH+RD5AQD8DPwIBwMGBgwCAfwB/vsI/QQAAAkBBP38AgIACvsC+/sA//8J/gb9+wP68vz6AAQD+vf5DgoABAQDAQH+DAIFBvgACgMDAfoD/wIF///+Bvf7A/UG/wf8CAMHBvsEAQIGB/v8/w37"],
    ["infection-protection","health","8AUA/Qr3A/8M9PgOBQP+9PgMBQX3AAkIAPz3BRH58wUB8gID+/gAAgPu9QEF/PwC9/wG8AgM+QIK/QL6/wf5BQAGCP0H+v0D8AX29PjtCf36AvcH7Ab0AQf3/PUBBPr8/gD7+//6BO//BgMM+QD5+gYHBwkB/wECAwDq////9Ob//QIA+QYL9gEEAAYBFAT68wMHAAv7BgUGAP0AD/cC/gAE8AsMBe/6Bvj+Cvv99wv99wQB9wQA/f77DwgC+PkN/fT//wXt+/0GA/75+g/5CgMIAgwJ9g0E/vkDB/7+/vkNAfkC7ff0/Qf7B/z59QEBBwEEBfPxAgcB+f/8AwkBB/MFBv/y9/8LDvT7BQ4E8/4HE/79+gH8AAP5/A0M8Pn/AAEB//kD/uzvBusFAOz9C/H9+/77+f39CAX/DA/8+An98/7tDvv6+/ABAAIJBwEF/f7+/PL+Bu4U8/f/+wL1AQH/AAH/7vwCCQAKBgr4Af0CAPcGBAP/DwHq8v38BPf3BAYC/QIO9Af5Cv/7/Aj+//r9BQEC+vMB8/0DA/7+8vT/AvMK/fkBAwr5BQ0C/gkE/fsB9foA/vn+BBL6/wX9BAAB+P74BgT8/wn59gMD9wAFBPsOCfsC+gIIEP/3BPgD/ggB+Pr9+fUBBRH4+vz/Bwv2A/0FEQH7AvgBCAQF9AT7DgUA8vHtDgX19wYJ/PUEAwUDBAMIAgYA7fsC/PAJAQcFAf38+wD49gnq+wT2AfnwAPgLBfgFBfn0AAQG/+4K//sG9gXx8QTu/foB/QEEDA32/w7xCwUBEvz+9/fx+f74B/31B/QE9fH5AQAIAQD9Bgz8/AH//QkE9Pb+8f4M9vwM/QL+C/z9+v0A/AUQB/z8AwYD+gn2BAP7DPv/B/T9Awb0Cff9A/IE/AEJAvUEDgj/APL8/fkD+gUI8wT8/Aj2D/gJAQAG9wACBPgKDfr//gjxBgv5AQAC/gUKAAz8Bf8FB/gD8fn3Bv4I/PwF/gABCgT19P0IAAv6Av4ECP3/"],
    ["first-aid-assessment","health","6w0EAQLxCQPwCP8DAP4A8Q4L8vz1Afv6Cfn7Dwj8AgUAAAH5+gIL+AwJ9gkA+v4EAvwE+vrzA/0VCfL4APkC/BP8DQ4A+f3v/f8G+vT8CPoC9PoB/e4GAAMDBfL9BA4B+Qn0EgkL//76AQL6/f7+B/L5//nqDPv3AAvx/gfxDvcEBv0D+/8I+QLwBfb+/ggACPf6BPACAv0EAgb/B/4D/vsDBgEA+gD+/QUGAw7v+foO/fkC/Qf3DQb8B/wD+QIG+PMA+vn6+P34BgIE+QUF+fsOBP37BP/8CP33/AgHBPwB8wkL+QUN//IK9g0LAPn4A/H8AQf9/Ab7/AIB+w73CuwJBw3z9fn4+PUGA/sEBO35AAn7//0EAv4C9wv+7AkA/PkJ+ff/+fwQ/QUH+f4AAPD6Bgj//QH8BQYN8vL8/A8CDwj6AfoG8/oF8/f49PUHAPb7/PoE/PQS9QH89AL3B/799gj+/Pbv8wj0+QIF+gb/AAD78wMD+AcH/ur++wX9//0FAvr/AgH9+gQKCAME/AMO/v8BDf77CvP88gX0BPX4APcHCAUDCQkK9AcC+vsGA/f0Cf30AAwD+gT+CvoLAwT/9vz+9Pn8Awf+9/ADEv4MCf0E/Pr7CAYCBf0C+v/8DAD/GfYLCP/8/fX6+/P5Afzy/PgEAAUG+fgI+PcDCf3nEgX1+PbzA/T77wUICQgA+AQJCPD6CP79DPYG/On2DQgE/AAFBgMA/fkHBgwH+/DtBf39AArxBgAF+wT5EfIM/AMHAfz6Dfj7A/UI9gDxBAT8APoOBQX/C/MF8g37+P72A+77Bwv+7vr2AAgBAwEI+AMC9vH8EfQI+wHqBf0M9P8DB/7+Bf/7Av4ABAYC/fcCBQINBgb99wL88vcH/gME/gH/CQsG/vMGCP79Bv8BChP6+P8CAgP6/Qj+/APz/gj9/vb/Afr/+P4P8vsBCgb6BQf9BwD2BQICAAID+wH8BQADBgIF/gv6BP7+BQTx9fP3/gH++vwGCwL7BgQICAEF"],
    ["recovery-position","health","/wzr/wPv+QQC6/wF9/P79PoMBf8EB+oH+f0D/OwE7fcC+wAMDwQOCQEP//f+BQkD8/8B/gcEAPMB9wf78QT+E/v9A/YE/Ar/+f3rAPcC7QQJ//sU/RT8CvwF/goJ8QX8B/v4+gr0/ez5APwCBfMEBf0F8AbyCAQBBgEM/wkBAPr6/QH5BRH6Cf78+AUIBwj+/wEHBQIJ7AcL9/T+AAcJAAUHC/0B/gL2CAL4CgIFAfv9/wYAAf0CBgH7AwP89/7+Agb8+gf7COsBB/34CAQJBgP+/AAA9/j39/z3Af0B/f4A/goGBAT2BfoB+QX9APn3BQwCAf8ABAYCAvz/DP4NC+8J/Ab2+/f8+O70AAMC7fD2CwoDAvr5CP8E9wv7+f77CPsDAwUEDwYEC/8E9/77Cfz5BAAG/wfyAf0H+fAM/RMIDAz5AQoFCPX99gIA8fj6B/36CAIL/v8QAgX/DfkLBAkC9vgF+u/uAAD5AQD8BPj7CQD/9w3/Bfr6A/oEAf8K+QcK+QYL/Qb/Bf8JBAn4CAQFDAoAAvn3CfcA+/kGB/LzBgz+/f75Dw4C8gsAA/778vz+BPoHDg/8+Q3+9O0FAwEC+/sC/Qv5Cvz8+PEBCwYIAgT5BPkGBQv4AgP3BQcB9gD8CwgAAQb0AvT59/n3D///9/z9CP4D9vsCAAsNBg3xF/kPC/PxDgLy9fz6Af8A/v4BAQz89/n89v0KBP79Cgn6CA77EggDBQn58gP7ARIJCf8ICwT38/L1Avr5//wH/v4A9QYEA/8I+/oA/AIGDf0MAwfv/gT/DwQA/QH68QMKCAn8CPz7BQcNFQELEvgGBfjqAPAWCA35+fkJ+/QE/P8G+fT9//4B/QT8/f8L/fYHAgQK/Qv6CQH5+PkDBA30AAIKAv74/fX///L8CQkB+f37BQH7+P4G+/8K+vYF+AAAAv8N+P0L//zv9/QNAgIFAvH2/gP7Af359gQC+wX5Cf4C+QL3/voG/AAE/v779f4AAf73BvwIC/X2Bf4BAQUD"],
    ["opening-airway","health","+RT4CQH48AkD7/4C9vv79fkHCAUH/+cE+vH1B/v6/PcA//4WDQMNABMJ+vsE/AAG8fr+CgL89/Py+AX19fXyC/oCAP4DAg8E/gb28PsB9wkDB/IL9/0EAgP8CvEN7/76DAIH+A0D/PEADQMHBfoBAAQB9vjzCfcH+/wJEAD6DwEDBvbv/RH5Av35/QH8BgX8AAEKAwIM+AMB8/vw/AcOAAgABgAH+f/0B/j4BgkAAAYF/wD4CQD4BAEAA/n7/AAJ9/3/A/7+Ae/5/vrx+wcD/QT/+vsF+/oEAPcFAfH/+gD9BwIHAPYAAQMF/QABAffuAgj/9AT9BAf8+AQKBgH9C/kLBBUBBPsE8Pn5BP/67u75DgcL/QLyCPH5CQb0AP4B/AkE+gjzEfcBBfkE9wUQCQQFAP/37gYA5vIK8PkQDf4I/PgD9Q8aCfUIA/cH+/UJ8hEDBAD8+/UK9AwGCAD2/BcLBPsIBfoJCg/6BAz5/v36BfcD/wkH/PcL/AX89wQP+gYG/AIFAwDx+QL5BAL+CAcMCfwA/wn8//oHCvv5APj/CAEQAwT6/v4DBf/7Av8E/Pfx/QT8APwH8Af+Af32Av3+AQsC/wEEBvr6AfgKBgH8Cv//BP8BAAcEAvb7/vcE/Pv7/fkD/wIEAQD8+f39A/wNAAj+/wL99/b+AwMK/ADoDv0P9u0IAADq/wMDCfr48PsABRAB7QL1BQgI9gj4AQARCQ4IAf8GEg/+AvME+wECBv0IAfwH8/nv7Pn4CAwMAwMDCv3/9QgK+vf6Bfnw/gYC/gf2DvsB+hD+/wv1AQkJA/MLA/YK//sB/vb+8f33/vv1BPEJBAD8AvsJ+f/3+QAB+/7+CAIJ9wL7CAYSAwn/BhEHA/r1+AT6/hL/Bg8AAQYF/PX7/ggE/PoE+gkD9ff8BAcF/P3/9wD/BP0CCQIB+wL1+fcH/PwEDAH58vf9BggLAQH9BP8A/QcA9QH9AAb8/AAHA/f5+vzxAQUBAwQI9gILAgr4+vgB+/P+/AX9"],
    ["patient-warmth","health","6QT+BvP88Pv2/PAL/P0O6wABA/v+A/UM/fwJ9wPxDQsBBQ73DgkCCw4FAAoGBfL89fMC+wn8C/wHDPQC9fgF/fT4DgX39vv0AgHtCvPwABT+Cfj49gf9AwIABfQa//MJCgX7AA4EBfXw+/cHCvX3AP4GBgMJ+wn0DPEFB/r8//X/B/34AA8T+gAIAAIBDf8AAgP7AAkR/f389g8CBv31DgcA+Qj//AL+/PX3Bv/++QD+/v8G9wQDAwUADAMK+gQL/P0GAQD8//4ICPwCAAL8BAIEB//+/QMEBAX5BfL/9wD/BwX9BP8H/Pr7/voBA/4BAwYEBQP8BgcA9wX5B/0A/vcNBwgD9fv2//nx/PgBBfP/A//8+A0EBPT5FPwT8fsJCgcE+QYHAwX8AfcBAgP0DPH//fcKAAgH/Qn4/vwJ/QT/+wAA+/X6+Pv7/Q328QoG/wT7++0C/v0JDQb3Cvr4B/sE+/oD9P796vYICwwN+gcNA/v8/f4EAv/zAwT//xD0Cgr4+PoLDfr7+wYHAQ/39wX+/gMLEAUF+v8HABD8+vwI+wUH+vsH+/r9+Qv+/fkD+Qj2+fz6+QgJBQcCAQT9+vIA/wL2BAf9DfDz8wIE/QT+/wAQB/sK9wj+8QT3Bu4H8fn3/v79APz7CAb6+P73DwEOCP4Q9AQFAPsFAQf4BP/wAQUF8/DzAO/29P4JAvsCAgIHCPQN9vz29PgC//UAEgsJ8/n6/fHz/A/q/fX3+gD5+AYPBvf9BP/+9QACBv8CBvj68Qzw9gkCAfcEDvkFCQ73AAoC/gz8DfkD8QP5/gT79fz+CwMFAPb8BAQJDwEB+Pv09f/3+AEJ+vcCDQEHAAgCAPv+Cf0E/vkAAgcQ//kC+/z79wP7AffzCQD7BwH5+gP8BQP/BP4EB/oQDO79DwL18/j6Cfz4CQYG8QMA/AQB/PP7/fr///cI+/v5CfwAAQgECvsB/wII8v8E+AT6/PYD9wMF+/nvBAIGA/0F/gQD9Anx9PwC//j0DAEDCfQI"],
    ["patient-movement","health","7gUD/gYDBPny/vAG+fn6/fsGBAT4BgQB/f79BgD7CAMEE/UFBwL59ggG9PX+/vj9/AIP9w4B/AEC/fgH/QvtAwf2Dvj8/AP+BAb7FAH5Af4A+AIB/PgFD/8BFfMHB/wI+QP3BgT8CwTyCgIG9Aj0DPX+CPIAA/sC+Qv0BhPzDvjz7/cGBgj29gQA9f8FB/jzAAEP9vYKAwL7AAH7DQEI9v79CQAE/QX3ARH8Df/0+gYNA+/9+QgEBwf6BvX+AvoF9PoC/v/9+fIEAPb4+wQBAQECEwf2/vYIDPwD+Ab8AQX9/f8LC/QDAAX5+vv/Bf4ABAcA8Pn3Av4LBg/5AAr+BPkOCw4TAQD97ff3Bvr8CQIBAQz5+gz0Bfj+BwcDAgAJBAsP7AIGCwf6AAX6CwICA/UB/vsEAQIHBvX2BvwN9wQL/AP7+gcMAgIY7gzy7v0O9/b39gQA9/EJ/Qn6BPz/AwcE+Pn5Avv9BBT8BQ3+AgAI/v76Avb89PYGAP4D7wT8APMB+Qr4AfsC+fcK9Qz2/AIAB/kAD/oGBPwC+hD4+Pv/+vwJCAoHAQ0Q/AgBB/cDAgH3Dv3//goABwf9AwD2AP0NBQQH+wX4CAYDAPIKCAMT8AIE+vz9+gH6A/cA+PoJAPIHAwIE/wj6+v8B//fxDv0F+QADBAYBB/kFAgMNCAXoBQkIBO35APT69AgI+vv+/gYO/+4CCAn/8PgQA/QCAf4P+/0E+Pj+CQf5+/QG//ny/QcCCgH8/gb1//36APgBCvsB+vf18gL2CPH/A/j8A/v0AQED9fcLBvoH9wcMBv0A+QUL/v8I+/QFAwj+CvgR8woF+wEECf8J+u8BBfMI9v3++/7/Cfn8Bvj4+A0IAQH8CAcHBBH+8/nxD/sJCf8A8gX2AwP6+vj/Bv0F/fkCHgj49wIABvYJ+wQK+v0I+QH3BPH/BAL2/fkG9v3/CwEA/QoDAPv5AwYEAfL6/QD5CP7/CPkI/Aj//P/4/v/4/fUJEgby+/T9+gH8BwT7AgMD"],
    ["head-to-toe","health","8AwRFgbxDAL5/e4F/fYSBAIGBvzxAwECBv7/DgX9/AT/DQL4+v8E8ggEDhP4AfD+9wgC8gILAAUNBP0HAv/0AQv6CQAC+AT3/wn88v38Bw0A9/0F+f4A8wz7Aff+9AQE+AP0BAMB/vL6/gT3/An9Cwf8AP3x8v//Avv++AX3B/DyC/z6/QED/fv8+f//Agj+CgIFCAQB//4HBP79AQcEAvkIDAkCAQb7Cxj19wIG/gwL+/YE/QUADwIAAf8DBAD9+gj+AAL8Avbw//709Q8KCvgB8Qn6/PwDDgj88QH79QcJ9Q4LDO8I/PsAB/sIBPgA/QX8/w/9BQII9QYIBgn9/fEF/gL57/T58P7/CwAB/O/1DAII9voPCff68RAD9gEIBf7+5wXzDwEGAP0C/voB7foDB/MIBfkCDvcF/P/0AwUI/gH99AUE+u0I7vb09/QC//r18vsKBfcP+wT8Awj4+wL++vUPDPLz+wX+DA4J+/78AAb+Cvz09AMA9+8DAvvxAfsS/AQICvX5/gIFBwL/AwQAAQcA+/X0Be799vn+/fvz//kEBP7+AQ4O/AAL/vQOBfb8Cfz9/QwAAwYDCPj8B/D3+wMC8vz9Agb68f8FCAkCBvv7AgEFA/v89/4A/P7+BPn+CPwDC/7+BAH/Bv0EBf8B//oB/AAA8fj7/wMF/wf7AQgHDPcKB/MF9wb/+A3oDwL5/PYCAQED9/gODQH1+wQMCf74ChP5Aw4BDfMC+gD+Bv739/8EBgkCBPb//A0DBPr/Cw4E+fUD/wD59P0I//35/fn9+vcHAAH88/vxFQj4/foCCAQB+vsLBwIAA/sK/+z+/OwKBv35CvsH/voE9fwI9wMCBgz/AfIG9PYFEwIP/Pz8AAv/+w38//MCBAQA+P8EAgkC/fn9DgMGBgL/BAgC/AgIAPoOB/n3Bf72/vkC+QP3C/gH+wD8Bw3//Q4BBgr6+vb/B/kI8/v0CwD0/RbzBwH4Cgz++PoCAgH99/n++vP+EvsEDPwAAvr3A/sF"],
    ["trauma","health","9ggTCAn2A/j3/fcE/voI/gcIEgbuDv8EAPMGBgb3+fsCDAHyA/cAAAr8DQf1DQAD+wYEAgMNBQ8GCv4IAgDwAwL/Df76/fv99Qr5+vvxCAMK8QD8/f77+wIFDPALAf4JAPz5/fICCPbvAf0G/f8CEQQLCPf88/8A9/8K+P30FfX6B/UEAgID/fr0/Ab/DP/8Bv4IAQwVAP0G8QH6/wf6+fwEBA4F/wr8ABH8EwEJ+BABB+4D+P/6CgD+AQEDAf8A6wAJ+wP/AvcA+vr76goFAP4JB/8AAgMFCf709gED+g4E+wEG+/kE9v4BBPj5APkGAwEGBRD1/AAF/fsDB/kC/vYPBPgF6f7t8/vxCQIAB/b/BwME6gcD9fT99wj6/vYFAA7sBAoDA+4HAfUK+wMHAPcGC/wN/PQLBgsE8wIC8wYB9RX2+fcF+AIE9wD5DAQQAPr5CgH6CQIL/RLwA/oBAvf29QULA/7/9wT/CgEGBQr6Af0D7ff3AwMJ+/sAAhD2+QH6BQkG9vYI9P0EAAP3+wL7Av/z+QL+/f8B/QH+//34/v8FCPoI9/wVBBEL+/wHBgDx//0FAvcIBgT+AAL6Avj+/AD8APP0AwnxAPwGAgD/CAQB+gAD/Qb2B/z/BPML9AcCAvvzBPcEAP8DA/0A+P4C/ff49gAKBfwNAwgJ+gvrCwoK/gEBDAD8BP0K9xP4AgQAB/H8CfoM+O8YE/kDBP38EfkA9xAG///8Cv8A7wX09AHyAvUG/QsEAPkH/wH+EAUCCP74CP39/foD9/4H+gf89wn5+w39EfX/+vv+/wHxCf/69gn+7/r/AO8FAPwU/AUBCPMGB/z7/vb6/QAH/v39/fr+BQH+BusD8/sP/AYOAP8F+fcE/Af3//oEAAT5AxUFB/0AB/MPCPj1A/UG/wT+AgUIAvkGBv0MBgr/AQ7//woD+/sF6v4A/PwCCgQCAwL2+QME/gX6+vr7AgICA/r2/Q3//AT9/QIB/P37+gX8Bu39A/cECv3sAv4JB/kD"],
    ["vomiting","health","+fwFCf3pCAf4BPfuAvTpAfQA/wL6+ebuDg4FAg8B/wkNEgsEAPj6BPX9AgYA9f8HDvzwAfsI/AP//ff/CgT9CvkO+QD/+AkRCwQCA/L/8xH7AvwA+fv9+/r3Bf77/v78CfX1B/n5AAEM/gf7AgDtAv/9BwD3/QgE/+0C/vX3+wL7BPP9AwcCA/sH/Qr6CgD6+f8MDwEUAQIH8wX9Avj3APgGAwz9/QX/A/YACAAFBfkC/gr/BAMB8/b9CP39AvoE/v8IDgYH/AD59wj/+v0F8/78AQIB/wMBAxAH/voE+wEFAfwBBAYA8wYHBf4Z+gX2/fP9/wIOBvr89/0GAffwA+v6/wbv2wQJAPrs/voI/AYHBfwG+/r79QYNEPwF//MPC/QEBgEG9gny9AkPC/X38PoE8QECEfwD/Av3+wUH+gwHCPwM//0H/wH8BwAD9u/5Cfj4BgwG/fkC9vTzDwP//AEIAfX+Awn2B/QKCO0F7QECAQUD//oQ+wL7/gD/AgT9+QD2BQMA/wX6B/wGAQYC+/ICAQ0GDvf//fb6Bgv5A/4G+gYD+QP0/AP/8Aj/Cv4AAQH4+QgBCvb//vkF/PT4CQUF+wAF+wQB+gUB9P0CAwP8CwAO/f4E+foIBfz1+vL5/QL/+wcC/v0GBv8DBgD28gH3Cgf+AwP4Bf/4BP76/v/vDQEN9vQECfwEAvn+/vX4CATuAvfw+PYE7w0I/Aj8/PgHEfcCBAkJDgEJCe/0AAoB+wQH8QEE/gj7BwIEAgb6Cwb8DRL7BfsFAQD8BPr/+/oJ/f/y9v3w+ggEAgEC+g397QAFDfj8BA0FAvgE/+wB9vwN+fcP6wf9AvYC9/jy+wsL//0CCQgH+wP+/Pz1BQgF+wbz9wX79v//+wT7AgDz+AoA9wH2/ff9/vz+//n8/Af+/AkBAP/9+/8MBvgAA/gJ9gr8//0H+/j4BQ/yDAj/BAn0/AEF/QIKBAP2//sB+wLuBf3/BAL89gkC8/309PkC8/0HAhH+9PkD/wH3BvX7"],
    ["fever","health","BPz3CwD5/Pj8/fH6AhoL9fQE8wMG8wv77wft/P70Cgb78Pj1/f//AwcBCATuEvjz/vj5EvQHC/4IBfr7BQny9QP68gYL9/oPAP7/BQYI/gcK8QP0CQAD+QIE+QMO+gYGAvnu/PMKAf/7DQD8AQcLA/gGAgEOBQLsDPkA/gL5/gMJ+foG+PcHAvYJ/wj/+//6/f/8Df0HAwf9+fn+Agf+AgL/+QAE/gIMBAwC/vwIAAX+APT49vwEAQYCAf8H9gwA/v0H9v79+fsA9ggV+wAF/AX+AwIK//v+Avf3B/4F9/UHBPQK8PsNCQEG9ADzAvz/8AAF+QnzCgEHCf/7//35B/7s+/fu8QgBAPbu/fMZAu3/Cfb99f0F8AX9B/z6AQIJD/YOAQ778gD++/r+Af/z8PT5+wf6Av8DAQf3BhAI/vsH9wX9/vH89/f9AQwEAfr7AvMI9/kDCvsH+wL/Efb7Av8B9AP9AfsQ9AAG/v70/fz8+woC8QT/+A32BfL6+QP8BvgL+v8F+w35DvvyBv71Afj6+wQLAgYE8/P//wID6vwAAQb0AgMCBgP3/f7wAv7xBgD/CPMMDf/2BAr9CvYFCwP3CwECBf7//AMFCwj+//8AAxAFAgUCBQwIAgIJAQHzDQH/Avb8AAEA//39CfoA/wD9AvYDCQUE/AP+/AD87v/v9/j59f0JDQv//QT4Dgz3/AYEA/P9B/0F7/8ABPn/Dw75BgUBA/MBBPry+AEKAPP7Bwb9/vP8/wEL/PoD/fIBAPcB/wb2CwD1+AQC/AP79RH1Bfvt/Qz8BvEF7gn37ff9B/7++wH9+fgI+fYF9QH1+AP7+gAFBPQK+AP7+vj3CgL/BgYGDv7/9wEBCwEA8AoKAvsU//77DPzwAPv4DvH29f3/CfIE8/cIA/4GAP/vBwgEAP/1BgAA/f8M+AT19w3+Bgb3/QAD9Q0ECAT8/Ab+/AAJ/AEABAwGAfsJAPwQ+QP/Av/4Bf8VBwX3//P6/Pz/CP7//PoHCQD7Bff49fMH"],
    ["ear-infection","health","9fjw/PnxAgfwAQL17BYE/AUR+wH/C/rn/PIAGwL/7g0G+/8DAPr9+AMC8QT17v7//QH6D/b9BwQD9fQCC/MCBA/9APj48QT+9vwEBPj7AvoK+w7w/AIQ+QD+/gP28vH9AAL/7Qb9+gr+A/j9/AAA/PT6DQ0CBP0IC/sJAAQAAAUC+wUCAA37DfUGBAAA/fgH+QABBP0B8wX4+gMJAAfuAPwGA/8B+/T6AAD0BvkIC/oI/QEF/QkFA/YHAv34/voR+voDAwQHAPzx//wEA/j5+/MCAgYCBwgC/QEG9gn7BPwE/P0FBPwADQkIAf4H+/b7CAYD/fwO/QX8AQIHCAHw+O0L9wr57QD37v/u/+8XEQgFCAAH/QUC+vjsEgwN9AYJDgcICAICAf0DB/QF9/cPBgn1//4N9wb6D/r1Bf3vCv0D/P71/+wB/gABAAD79wIIAv4G+/8FBv78Bf7r9vb8+AEJAPAKAAAB7vsICfcE+wn0AgcL/woB+wgBCwT4Bgj9BA0GAPwPDffzA/sCBgH7/fX++wf9B/EC/A4PCBIF7RAC/QYIAgL6//oF9gQDBgb8AP/7/QMA/AYBBAQHCQQADf36CPb+AP78AAv3APn8+vsE+AoGBAQG/QL8+vsA+vf+/gn5/wj5Awn7/QMIAPkABAEE9vkC//8D+P38A/8EAwDsAfL///4A8vQB9wP3Ff4GAgz8CPsLBuz6//8RCQL98wj5BP8MCP0GF/r5A/vzEP8GCQH8BQEKAhkB9A8A4wAEA/MH8PT89voI+gsB9fj/+AcC/P/8/fcQ+AII9e/1/gD2/Af/AfsI++cDCQT4/PwA/gH///cK+fb8BwQDFAf++P4LAwMFEP76/PwADAjzB/r8/vcEDQHuAwYHAQz/BgD6Agn89wDy/ff9B/MF/AEF+fv+AgD9+v8GBQEE/Qj8BgL4/AH0Agn8+fsT+f4F+f39//sGCAD6/wMB9gH3A/sE9wT4/wD//QEFAP0FAQb6/gT8Awf69gT3CfkD/gcD+wAD"],
    ["skin-abscess","health","8vUC/+7g/gDu+/QD/vEC+gv/AwgABAcCCu8SBPwIBAYH+Ab4CPbv/QXv/BX59QkG/wsJ8AAB7vkKDP38Awj5BvgDBgoI9ALsAP0AA/n67/r3B/r7+Pn9BvkI9PP6BQAAAfr9BwEF8BH7/QsB9AX8B/QJB/v5DAP29gsQ9vv7AAMAAv4AAAT7Bfv4/Q0CBf8JAf0HDPwFAfT5BAQHDgf4BgD1/gAM+f4B+An8AgUJAvv9Bwn9Av0L8f8CCwIRAAcG+v4D/P0E+/QFDvIC/f38AP4FDwQIBAwB/AQCAAT4/wL7CAH6AvcFAAH5Awz6A/sDAPz7/AICAAL6/gH6Aw0AC/v7/w/97fv9BfYJ8QYF/BLvFQLt8vAJ+fsFBAEOCAoD+wP+8fsA9/0MAwH/CgMO8gMC/PsB+ggEBvwF//0OCQL4+PX7B/X0+/wBCv4IE/zyCg38/gAHAfMGBPkKBv7tCgsE9Az/EvYF9gD5Bf//Dwj7COwE+QgQ+gcMBgIA+fsHEf7+/gYEBAL2Bv0NA/MGAP8REAAC/gIA8usOAgr8APkH+QcLCv0FBQP+AQEHB/r+B/8E8wL3Av79+wnzCAYNB/8CAQsCB/gE+/37Bw35/wT9AwAA/AX7BQgE+AT++/gC//0B+PwDBAQB//4JA//9AP8JCPsB/v3+BQ4F+wcJBfz2/PX+7vDxBO3x/vsI/gHyBP4AAvgK+/39/AsCAgETAxL7+O/4+vMADfLjBAXrCA8K+v7+Agz7BQcD+f0EDgX/+/4D+wLu+/kC+Qb/8P7yBP0D/gr3+f8ABAX1+wYF9xD9/vMC+A77Be36AwQA+/f++wwC+gMB+gYB9gPp+v0D+wgEBAcI9AoAAgTxCwX+/goGAPsBAAr79QL9BP78B/gJAQUECQr9AAH3/gwO+v7//fn9AvX2/QAO9fsAAhD7+ggE+f0F9gII/vUT/AwH7/0G+fsK/vsHBAv9+wYHAwD8+v//AwsDAAb69wP7AwT6CAL6CP8ABQf89gD//gMC+fr7"],
    ["wildfire","safety","9vYSCAoL+gD9+Pz0/vv99QQHBg8i/gP27RcFAgkKAP4AAAACAAf7+AD5/e/2AfkC9OX1DQEG+/IL/vgLDRAJAvn/AQAP+fzz/g78ExAF/wAC9gz78vj5+wIBAgsFAwYQ/AQB9gvzC/4EEf0I9Pb/CAEH+QQDC/0L9QLx+/wCBv77/fgE/Pf+Avz5+/4CBfoDCgEGAQkGAP75A/8ECvz0//z7Awf6/PgL+wL59PcFCAgFB/UCA/oFCv/8APj+AAIC/wT8/PfwAfUDBvYA/vIJBwT+/gMJ/fgJ/f4KCwIA/fsF+v/+Bfb5CQL+/gb4/vUD/f0J9wMIAgcBBQT7AAkAB/nvEA0D/vbw/+/+AQULBAj7EAIEG/0DBPAKAOkCAury+fL5CQv89P4EDQL56P/tAvnuChr+DwjzAwII+xENB/P8/vsGBfvxAfkM+Ab+BvwACPoHBvsI9vL9Cg/+Cv8C9wv79/wH/wTxCQsQAQr3Cv0AAAf4+/8NAwgD9wQDA/r6Af///QD29g37/vv99gj4/gEBBQcG/wIK/wL7/voL9QQE+gABBf78+f3z/fP3Dfr3/vr+B/8GBv78A/wG+gIJAPoD/vb4/QMA/AACBwD9/gMC/wP+BgUBBvsBBQ8B/wL9B/75Av4C/gEFAv3/AAX//f8AAAUE/gQI//b1+QAH/gv7CgoWAf4A9w7z7wL8AwT7+/L7/A38EfoCAPv9/PoB/vr2AQz8DvP3CAAK++b78fnu9/8B+wz7CPf0BAH+B/kJAA0DAAnuCfn4DPsCBwgI/gvzAPn5AAH7CAMLAgQD/Q30Bfz9/+8A8//4BfsAB/4QCP0B+QIP/xL5BPkH+/T38f37/f8ABgr6/AT5AgEFAfgCAwwMBgkHBwMDBAEDCgH/AwYDAwD7A/4CBPf6/PsBAAkK7vYBAwMPAwsI+gL6Cwn7AgACAf8D8wDz9vP8BQT/Av34DAMF+ggGBgXy+/8DCQvxAgoL7vr7+wH39fkF+wAF9wTwBgT7/wcRCv34/wEG"],
    ["tornado","safety","9QgEGgP6Bfj96wUFAR4FDAPzEPcW+PXx/gUICPv+7/H+A/T69AIB//ToAAD38vYG/AT77fH6+ffvA/v19wbvFgEFBAf68PUI/vYC//cB7/r/+PkGBAEF9QAAA/kJAwwE+PQA/wL3/v8B7PoJ+fv/AfsG/QgIBP0PAgQIAPkA+/YBCQQI9f4E9gD1AwIBAfj9AfcJAP4F/QMK/vkED/r9AgcKAAT4AgACCfnw/v8BCggD//8HBv0IBP37+voFAQMJAgL6/AEC/wDzAAMAA/4E/RD+9PYDBf0FAwUGAfr8AfcCAfwABvsH9v72BQoC/P7/AQEKBPwA9Pz9/wL5AgECCOn7ER/2Cgj2FfIE8wf/Afz2Cfr/CvX8/vn7AAb/8wD89Qv5DfoB8gMLAA8LA/vx8gIA+PoLBwPx+vwF+vf+6wb/AAb29/UD+wgMDPz27gX7/ALzBvwJAwUG8QT1AAz3CfUX/PQB9Pz58/b5Af4A7gQBEAMC/QYI//kF/QMCAf0E+wX29/gLAfX5+gYE/wMF+QIAAfsB+QT7+/kD//4EBfUECAf8+f///wMF+/z0+f4CD/cAAAADAgULBfz5AQQHA/r5+/34Bf33+/b19/gGCgUACfcI9vP2BQL9Bvv99Pv8BQX2AgX2AP4G/Pn6/P38BwH7CfoMBgb7CAAK/v4HAgQB/hAb+PX45AH+7fsO+Ab6DAjz8xX6//7z9gn/AQ4HAAMSAxz+Bu8BCAAFA/YF7vH3+fsHAfP+B/T69/j1APcJBPX99gEE/v32/wH+8PH3AAAI/wHrBfb4A//9BvwHAAj3CgL9/P4C/wTx+Qf3AfP7+gMKBP0LBwAA+PkJB/34+wIA/AP+/ADw9/8D9v/89/X9BgcC+QP6/P/4BfQGA/b7AAj8A/T/9/v28//99vf9CwPy+/b8APkBAv8ABwEH+Ab+Afv/AgcI+gECDfv/AAsDB/78B/z8A/0A/AgE7wv5+AMC+foC/Pv9/QACAf72/gMJAA36/f8F9ggB/P/6AQMO"],
    ["tsunami","safety","+gkC/Q7w/fT28urwAAj7D/ftEA4A//n8AAcBAuoCBA3/DQ7+BgL8+wb3Agfr9A4A9wn3AvT+8P8N8vMQDPr2AQ39DgLz8f0I/AT+Cf7xAQb49QYADAv7Cf8ECPT/CwUA/wL/AO73+hcA+QICCvEH/AcJ+v8I9fkP+wX8CPsBBAAJAAAGBPf/+Pz0A/kCBAAAAf78AAMB+gIHAfQHC/YGC/0E/ggB/Q0CCQECE/z3A/kB/wUD+QUBAwQFA/wB///37/z+Awn6Afr8BwQA+wAAAhH9Cf8NAQf9/P75AgT8AgAGCAYG/wD6/g/7Bv/8Av8EAgb+AAr3+f4L/AD+AhD/Avv/Dxj77/v2/Orq+PkJ/wn0/RUCAPX7/gD4Bwf1AfcQAAEH/P75+/0I9QMD8Pf+8/75CwvxBPb/BPMEBAID9AcICgQI+PT6D/r5A/j48wYL/wUCBA4IERD5CPr7/w0GBPj6/gD5BPsFBfb58wwI/BIJA/0HBP35Cv70+ALuBPj8Bfv1//wACv4CCAP8DQj9/gAC/v/8BAf7BQwEBgn9AfwAA/wJAvsICggH/wAE8/wAAA8A+gD+7/rtAAf/BvkHBw/6+AAL+fsIAwIC/Pb6+/UL/gYG/v7/AggGCv798w0I+fj8/P/6+gL/BfoH+gD5//4F+/cK/AQJ+wb2//gFCfr+BAED/gAD9ALn6PQDBPQL7gAJBwMBBwAGAAH0+v4AC/8WB/n59wL3+vYB8/PuCPX0+QX3BgjpBPzr9w4IAesMCP8B/O369gcC/Q39Cf0G/QQFAv8DEQEC/AL++voDBwj7+/78+Pv8BP4E+fkE//sGEAz1BfgF+QwDAPoL9QX8/gsB9A/+Av3uAP77/gv7BAAABwL7/vsHAf0D/QAI+Qf6BhH7BQj3CvoAAf8EAvoGB/z9/v/v/vwF+/wN+fz/Bv73C/YCBfX8+P31CQgCAfb/DgICCAHt+gAGAv4C/gH+CAAABP0L/vsECf38Af77CP31Cg3rDfz+/wMICPr8CfwH"],
    ["landslide","safety","7PsLAAAM7fL9APv9++8H9gH7CAH3DwD+7f8J6fwIFQP2FAb6BBH//wz69/rz/RHy///3/vcCAgsGA/QWBfz/Awv0CAACBAMABhALAfX3B/sKFgn88A379QX/DfkJAv8S/wT+7fnw+O/+/AYFAP4M+fv/A//37wAK//sDBgIB/PsE7wD4Af7/9f8ECgQF/w7yBP388gwBAgYI//8HBgoOBgcHAgQAAQH9A/X5A/0H+P8GAPgCAf8DA/70+wH6/AMDAf/8/wEG+AQFBAH+CAH5EP4A/QALAf4E/wj7CgL48/kJ/v74BPwE/QcEAQED/wb3Av8HBgwBAPj/AAEDAggEA/j/BxP3+fr07wT2Awb7BAj69AECA/30/AAJCe4F8fz3/xH39AQCA/Xt5AkF//cF8/j6+QcCAQISCgwLCOkB+hQIBQ4GB/T8AA8JDBTx/QIMAvsKB/ENA/T5C/j6/Pr7+AkBAAH5+Pz3Ce/4B/0CAvr5B/f1BPr9BAfyA/f8Bvr//xIACfb7C/EGCQP9+wP+/f/6+gEI+f4HEAH8+AYDA/QP/gEF/v37BAL29wj9+gL+AAP/BfsBAgP/BwAE/wsECQMDAPkB//v9AQL//QEK/wgSAvwHDPf9AwP/BA3w//34Bf39AwP0AvkK9/sCAP7+/gMFCQL9/vYAAv4E/f0ACAPs+g0I8gL15/QA9Q4J+QHs8v38BQD6+Qb2CQX59P8E+/kH7/gF/QQFCAcGAPn6Evn/BgMMAAcF+xEA+wT9Aw4IBgD3EgQB+/MCCBH5+vwIBgIKDf4CB/nlA/kO9wzwAf8GDv0F+gL+9/sEAAgE/vgL+gb9/v37+gD7CO79AhcGAvIJ+vH2//r2+QEABAQB9/35//fzBv7+AQQDBw7x/Az6BQT6BgL49gP+/Af9+QEB/P/58/r/+gP2/ff4CQj1CP4FAfH+CP0C/gYO+wII/AMEAQsBAwIFAQQO9A0IBAf+/QH+BQACAwIMBAn/9QEF+PsC/AYFAQMKAgcABP/29/4A"],
    ["lightning","safety","9QMHCwMEBu4A7vT+BhEG/wP9+AQP8f368gL7AAX6+/z3BPoMBfvt/woIAAL8+fX69PQB+wfy9f3vAvj+AfwAEAD/9PT+9PIDBQkG/vvt9fYLFP366fkG8vv6A+/8CfcFBBAIBQ/4DAj39gQB/Pj6CwgI/PUFCvQECgT2CQMJAwYFCgT+AAEFBwP7/fv///f0/AABAQcJ/wb//gQJ/Qz9+wH/BQH4CQH7AggABQX3+ggI/vf8+gH5/AgG+gUEBxP56wf7/gH3AAIH/foH/PYE+gEFBAoB+/0K/QT/A/r49QIH/fUI/vQBAwP6+gX3/P0ABAcD7QsN9PIA+wP5+gX4BfgABBMIBQPpAfjxE/z1CPwN/fj2CgAI+vbn+Pr8/vcDAQcCDPkB7gMK8gAK+PXq//fuAhP2+wIKCAD48ff5AQwE9ggBAfH3++sFAQ347/8F/AUMAPUAAAT99gH6+fz9B/cHDwMJ/QwFAe0L+wL6/woC/wX5CQn3/gL5/Qj98AD/AAT9Bwj1Av/7BQnqAfoE9/gDCwELCPUEAvoL+QECAQAGA/sC/P/6Avr3CQn0AfsDAPoFBf0EAvcC/wQBBvz8CQAF9wMCBgMDBwUG9gMAA/78/f0B/AAAAwMAExD0+AL3AgT77/kI/AT7+wP/CPz6BQgD+wP/Awf4Cvj79gACAgvuBQwSAfUC9AHq9RX7/QP49fv5/gkCCvz8AvkEAgEJ9fv3/QYBAfEBA/4LBOEB+ff69+oRA/z5AP/0AwH86wEJB/v7AfH//wP3AgID/fv9CwD5CPv3B/0AAAUJA/T79P3y9vwDEfQF9vn7Be/5AvECCPoA/wULDP38+/T+/BD9DP8C+fT1BP74AwMA8v4K/fQJ9QX+/Pn9APgDDAkCAv3n+QT4AfsD8wAGAvb99vz6DgX8AvkGD/sBBgT7/Qz/9wj5B/0B9f3//Qr6B/39BAQFAAD7/fb79Qv8+wD+9/YBAwX19P78AgIF+wb8/PkC9QMDAgX4AwT+8/vyB//6BAD/"],
    ["hurricane","safety","+vAOCQIB7PUA7N7//gb6Ffb3B/sJ9AMBAPj3/fz68A0EDwQH+gUL/vDyB/Hx+gr1/vj9/AQD9QAE7f32BAj2BQkCCwME5/UIAvMR//L7+wUA/wn7////BwL9AAf6BPj6+/77CQIDBwX7+AD6/gMCDAMP/QkB+/IK8wEBCfb/9wgLBf4BBQUE/Qz+BgH6AgLuAQD8B/8HBQcBB/oGD/wI/gME/AkJ9wH6/fsICgD//vkD9gL1AQj89/76BfgJCQAD9Qf3AwPzBgAQ/A8CAQAEAA8EAAkL+QIHBv/8Agf7/QAF//MOB/3/AwHz/gP3Bf38/g0C9/z+B/wDAgT7AwIC+f/7DBIC+wb1/vPuGPERAQX99A4C/fr++u0L/AL5+ePuAQgFDPEG9/X88AoH9PP6+PUN9AgHAAP59gUE/wkD+fv+9QL3CvX6BP8HBvb49fEI9fgLBQEGAPT/+AP8CggI/v3xCQ/7B/kA9fUBBgIJBQz8CBD2BAD8AAP6/P74/v4MCPsOBAQJAQYCBQP2/wYI+gcBBQIBDwILAvj79v0GBvMD/QIPAAn9/QME9QD5A/4DBfP6/PkJA/4D/gX/BAoGBwQBAAEDAPb5Cvf2Af0FDgQCCAUA+v37BwUCBwEA+v8JBAMBCQPyB/3++v/+/AjzA/0FBAEFAvr3CgAHB/T8BAf5AQsDBv8E+fb79wAHDv0L/+8O9Q35AP72Egvy+gjsBfoABPcCBf369OwJEPbu/Pv6Be8BCgMB/PICAAMAEPsTAAQLDAHvAQcJBg39++zxA/UPDwkDEwjy/gcHAfgBAP34BgQH+gT5Afj9AAkI+vkG/wj4/gML/AcI+/cJ9wn0BgoDAQED+gfwBP8K/gf1/v35+wP7/AQCEf4M+A4F+P7/CP/9BP//AfT9Cf0A8QEQ9vr7/vb69gYF+Ab/8vsBBBUDA/77/foB/gT2/AYA///9BvwB+P36AAQFAAEE+f0DCwf+/gf0AP75Bfr6BQgF/fvvDAYBCAH1AAL+/Ar+BQQH"],
    ["winter-storm","safety","9vQPGAICCvIB9/UF+AIDC/b6D/MOC/z4+vED8xPz/BEECRTvAAwA9/buCQn+/ewJ/fT19wcBBgcBC/v5Bf4NBP//DA7/+v/98/n88gLt/hjyAvkK9/fv/vr4C/oQAP/1/wr6BwP4Bwb38QgOCP8AAfn4BQkI+gUBCP4FBwH+9/z8AP77/gcL/fwN9P0E//f0//r2/v0EAhEJAwEBA/v5BRAEBAMDBAH3/f38/w79APf//PAD/v8DAQQHBv//B/wFCPv9+P4AB/4A9gYCAAL0/w/9AwIHAAMGBwL+/fr/+AL/BP3y/AD+AwD9AQIB/AT//AP9/AL/CQT7/gn7AgcDBAT3DQr9AQLu/fTv+fMCCAX4+Qv5DQX6/vP8BAQN8gIBAQYN+QEG9PD28g0D+vzqBf33+QESBwUBBRAF+v0DFAH3AA0NCOr0+gP/9/r76wIR8AYCA/X68/z4AgT3DPv//vkDAQMJ+AP99vr9DQD9+gj+/gcCCwAHBAACBgr1Bvb/+gEG/QYMAf37Ffz/Afvq9/L//Pz7CgANDwYC+gH5AQQXAgv8/gsB/AIAAQcG9QPx/f36BQf9BwIIB/8EBgwCAP73+/cB+wsDCPf98wcC/v3/+wj6Bvz7/wf+/v37A/oE/Qb/AgD1BAAC+PYH+wb++gEFD/n/A/0B+/EE9gL9BwXy8REU+fr79vro7Qj8AQoC/gAI9/oD/fjx+ALuCvb8Cf0AD/UHAPX27PYO//f67QT97vwECgENAPgMAPz/DAUGBPkCAArs+wIEBPIE/ez/FAL6DwH3BvIB+gIG+/8K9v71AAAF/v8KBvP3DAYJ/vwJAPkABw4KA/0IAPkJBAT1/wYC/wL9BAn/+AD7/P0F8vb7//0BAAsFFQf8/fcGAvr+EgcGCPsJBP38+/sCAPUHAAD6/P0IBgICBAUF+gcOAwP+/AL5+AYF/v/3AwgFBwP9A/kDBwX+//4D//4A9Ab19QcA8gP++QL/CP//BPsE+PP/+wf2AAPzAP74CAEG9v0O"],
    ["volcano","safety","+PH2CwvyAvT49OsMAQL/DQP2CgUT+QH86wYN6AT8+wICBgYHB/gF7wf8Bgzw/gIM+fYCFf0B/hIW+wIK/wMACvcECwcF+A0I+Qz5BQMAAA379Pvl+ggB+QDx+gIO+gAFCwf/APD1//wIDAQPCQcE/gsD8AT/AAIE9A33/AP6AP4CBwcN//gE+AMH/wL2BQoE/gX2Av/z/vr5AvcEAQr/Avz8+RIFAgT9Av3/Dv8L/fkFAPUM/AAODAQDBgP1AwL+Bgv9APf//wD/CvYG9wAABQH99wMGAAH8AQABAv3zAP8C+QEDCQX/CAL0/gQH/AAAAv4BAQADBAIHAAQK+P////H8/w3tCvz//gD0+Qf6DfH7BQMMDvv/BvQJAgEE9fsDBvgEBggLCvMD/P4MBAbq+/f9DwsBEA8bCQD6APn5EAH4+Pr8/P3/Av4J9Qj6CAQO+QID7/j7/f/2AwIAAPv+8f8K7gcEAQn8Afz8/QMB7AsDCALxBQP/+P/9/AsKAfPx+wEKBQT+AQEMA/sJ7/v6BvwE7wcD/QPz/PgIAQcEAvQD+v4PAfoLA/3z/gkA//P+Bf/9CQEC/RAFBP4DAgMEBQP5BP0A9/X6AAP6AQH7/vfy/P8GAfgDBwcKCwL27vsBB/v+AAQFChAABvcDAPwA/v4EBAsLAQD/9fUD//8ODwr79PQJ/+4G9fvz9gQDBAAIAvAAAxL4APfwCgDyBvP9AQn+CAgKAQTvAQH/DuwG/QX29ggU+/kCEQrxAAry/wQB9wkOBwX8CAHwCPUFBwj1B//79vP4/wMH+/L2BQwABAUEA/cE+vL1+QMH9wwFAf0ODgLo+/YU+wT8D/8HBPkD+gAG/hH59wf7Af75BPcGAwgIBAEC/Pf89Pv7/gX6CAD0+/7+DQn2BPv//v8KCgYBAAj/9Az//Q0QAAYC/fv8BP4DEvoB/fr9+v8E8wD5/P4AA/3xBwP2AwkLDAMC+PwABQQBAgMLCAACAPn7AAP0Af4IAf73/v8G/v4CA/74CAME"],
    ["avalanche","safety","7fAGDQP4//TsAPj4A+8IA/0ACPP9Afv8/fEQ/wf6/A38DA7uE/wG+Q37/AcB+vQG+fjuCgEHCAIIAfkK+v4GDQcEDAb6Bf0F+wj8CAL1/Bfw+AIB8AIB8wEH/PoNAfn8CQb5BPwK/fz++gf/9f0EAfj4B//1+f0CCPf++wEA9/j/CP0FAfgE+vQG+f0LBfz5/fz8/P4DAwAMAgUDA/sEBAoJ/wAJCv8B+wH9BQT4BvUC/vL9CP78+v4G/wUHDf8HA/38AwH8/fr6+QH48gAC+w0FDxQOAQIE+goB7wMK9AYNAwT3Bv39/fr6BPwR/AP9AAAA8w8DEfT++AoG//7qAgH5AgML+/bs/RL5DA/4+QH2/wP4BREAAA4DAvf++QIH9fwQ+Aj9BPr+9/0CDQkL+/v6/wP7/v8RBvz7AvYN8/cKDRQDEgH9EgkQAQH2/QQDBQ4I/vn88fsQ/gAICwgB+gsF/f0G7/oAAvoSAv8GBvUCCfX0AQEG/vz79QMPBw3yAfULAvz6/vwI+gMCBQkE+Qb3/PwH/QYN+fj6BvwBBfL/B/4D+P7/B/nx7/8D/PUCAfYABvURAwEABhAAAw39AvoEAQP8Awr5/wEA/wsDBQQH9foGEvcECAkEBgT9DvwF9QIIAw/6AAoMAQf99P4KAwL6A/oE//f0+wb/C/8B+/r8AgcWAAEE8fj1/w7/Cv4A7fkH/f0NC/3+9Qb0CPcBBfkNCPz7Du/zAvUFBvsH6/vs//kACAwFEQL6CwL2AwQO/QwEAQrwEP3z/Pv2+/X/HP7++vrvAvn9+vgB+f//+QUCAwj3A+sD+gHsEAAGBgQGBAAB+QYMEfkGBwIE+AP3+f4C/QT7Cwjw9g38AwoE+vUFAvsC/QL9BggBAgEJAQT2DwEIAQAF/wMK+/z/C/z4+gEB9vn/B/wCAAIH/woFCAQM+wMA/PYA/P/y//MADgD/DAP/BQT9/woB/gH88P37Bf8D/QEE9vn/AP/89PkIBPX++wrwAQgFAv39BPcAAAb9"],
    ["evacuation","safety","+AQRAwoFBgb68/f7+fT5Cfv7//4LB/IF/QAACQf+BQL7DAgGAwkFAgADB/MF+/EFBO8H/AgFAQMA8vwK+w3xBwQB+fAB+Ab/+gX5BP0K+QD68f4B+P37ChD9AAT/BwgDAfkM+A7yBAH+D/z1CvwEDgf8/fv+AfQO+hEGCAby/AMF///3/QL6+Pf67vj/BQT6BvkH/P0P/P34/QP7CvYC+Qb89vYMCP4P/gP+9wn/BwwB/vUF+AD3BQQCDe0JAAX8AAj+APnwA/EBAA/3BwT7+wH9+gIA6/YNCAYH///1/gQI9AUEEfsBCwX2/QDwAfj9/goI7gT/A/v/Axf3Bgr/CP0LDwMEAgT3A/P6+fYC9wQJAgcADP8BAPUE+Pz/+P0BAQQPCwT++vr7AgPnAgL2+//2/P72AfYH5/kGAP4J6A4D//vy//IH+/gB9AQBDPUM//3/+AgD/ggE+/wF/wr/BAAL/PcM9vr4B/YHAgr/ABIPAvb5CRL/E/kB/fv7+wP6/fv/BAT/BvkHAvYAAv368AwG/f8DB/YI8wYDAf34B/sI+/4EDP4C/f/38/8GBAEIBvz8+AD3/wX/BAj3/QH8CfMM+Aj59P/zDPr9AAf7AP8FAvcXCPUBBAIAAPn8BO0K9/P5/w38/wEDAAYF/Pf49wUCEfH0+gj9CQMNAhAL/Aj8AxD/AAQCBAD1+vH09fkA9P72+/sB+gj1/gQGCQkEDAYQCwT/CAD4+wUE+f767AQH/v0JAgb49P769gcLA/YDA+787AH3A/j2BfwW/gb/AvkBEO/9BfX3BvgBAAUF+RAC9/79/vz7BQkECfwFAgkO9vv8//4O/gLsBfD4Dfr9/AoAAfsEBfT9+A32+AX7/fwG9wf9/f/z/fcE+vAN+f/xAgv79goD8PcF//n9/ggE+gb7+wX8//oEAwAN/AYPCP0C/QAJ9AAGCf/zDPYCAgbu/Pv6AgD9/A78Cvj9BPrzAv378fr/DQIAA/wA/wH7+QX9/wH5CQT+5vsIAQoBDvb+"],
    ["disaster-shelter","safety","AAUVC//29/MA7+8BBe/4Aw8C/Q8MAf328/IE+fsFAgsCBQUO9QH1+wn8Agbu/fX6/fz0CwIA8wcB/Pzz6gT7EhP7Bv8I8+4I/wT+CvTv/QUH/gIA+AX7/Q36BvwC+P8J+AP6/P7z/gX19gUQAwX8/Q0E+fsECfL8BQD5Cfz1AQYB//YD/f8E+/YJ+fr8BAMDAvf3BAAD+fr7/gT2AAD5AQUIAwL/+wn3/P0HCfX6+hUE9fME8fz//QP8/v75BAMG+g33/AACBQEEAf/3+wAIBAn+/Q709AT9BPsPDfQH8PYH//34CgH0B/4F/PoD/ggBBQEN/QDzDfkF+AH6AvwFBvEGFAr7+/b6BPf77fD8DwIAAf4FBvsTDO8D+AAF9vwBBw4HGv0G+fcABAoE+Afs9v0K/wz6C/j++/wEFvf+8v8LAvny/PwN/AMDAwb4/P8FAv4CA/QFBwUG/AX6+fn3DfP98wL37f/5+/4M//kI9ggABQnz9A4BDfb69gX49QH+/AD88v8H+P36AwLu/wYD6QcF/f0J/QD5/wD3+AgBA+z+AgMGBQP9+wgC+v78/wIGBgT3BPUGBQj/AQH4BQj+Av4H9/35AgH8/fP4+AMG/v0BAfMF9fn9AwwL+AP6//kC/vn5CwD8AwD/AP/0+P/3B/4D/vEL/hEEBQAI/Pb9BALzChEG+/zxAPTr7fEB/P35BwX+BgsR+v3v+PAFAAX/AAsHBRL7BPoO/gEEBQf95vrv+/sPAwD8Au/7/AP0A/8HC/b87wD1+Pf9DO8T/gL/BQIDD/r9B/oIB/gTAvMGAf/5AQIA//0HAAPy+Q8DAfkBAgD7+wD99gEA+QAFAvADAP/9+QMM//X4/P38/PP+AfcLBvoH/gb6+/jwBfcB/AP3Ag/7B/wCAfEG+uwE/PsADwj39vz4/vkGBQn++v8M/gQCCvkA/PwD+QP/AwEHAQQHDPoBD/P7/gP9BAUB9wL0Af37BfMF//0DAQAF/P/2/Pz5+wP+8wAG+wH8Bv4EBQsQ"],
    ["emergency-alerts","safety","8hEFB/zxEwT77PTq8xEC//8EAwD//wj79/r4FAMA9/0A+wII/gEC+Qr5Bwn19eb0+wT3C/YGAPv1/PcD/QYCDAQOAQMI6fvwBAj59wT9/wX//Qf07gYG/PgEAPf4DwEK//n1B/379vkB9/oB/wD8EgMBEPQCCfoSBAEE8PH9A/QGAfX7AgQA//P6BQMAAAQBAwgEAgQFAv0F9wX6Cfn6BQoH/wf7AwEBDwX7Bfn+BvwE+fn6/P/+BfwGCPUAAA0JB/QF/gX5A/b59vHz+vv+/wMFAA4FCP8L/Q0L9PkD/AgCAfsE/vn5+QEBAfj98/gA/O8B+QIG/voIBf0F/AYFAQETDwXkAQkD+fL4/vr//fz+//j/Df369QLyBAEGAf77/PsD//cA/vEM+gr/9Prp9gD0CQMMAQH/8/QA//4N9ggE/v4JAPr4AgoCDQABAwABDAwD//UDBPoABgkIAQv7EQD87v/88AX4Bf4IBgIc8QMECPXzAgQACAr//PwCBAEA/f8C8gcFC/wCCQ8DBQIJ+wH1Af75/QYDAPn9+fwBBPz9DQD79QED/gz59Qf3+e4HCvv3B/76+AcE/wj9BQDzCPwJBQ8H+gf/A/ED8v4KAgQBAQIXCQH3BAb/+gL9CPz8/vr1FwX9AAEJBQT99QIGAAH7Dvb//PP1+/kCCwQC+gQCFA8JAvkV/ffm5vn2DwUECf4DAw4JCfL1/wADAgH4Bv/7BAL7/vT0Dv0UCP/99vfmCvUD+P79/vL6/fkAA/sUCgQDBQbuAP/8BgP//e8BDAz9/vjzAAf4B/0B+AAEBg37A+wH9QH7+/79ARL8Bfn/Egr/BgUKAQYFAwP++wMN/Pz99voC+g0C+gYHCf3/AQIABvwJ/gQI/wb7AfsGAP8CAwTuBgP/AfYNAQMIBfgM/Az08wf/+QQKBwYS/PoGBAT2///w+/YI9gP6+Pv6BAYFBv/5Bv//Bfj//v78+QL6/QL5/vn//PoDC//9/P30AAX5+gf9/vYFBgT2+/UDBvoG"],
    ["emergency-supplies","safety","/AcK+vgF8wcC+/kAB/f8/fj//Pz7BPr1+gH4/wP1BAoW+wIF/wUI/vAQAff9AvkA8gAAAgD6AwP3AwED/AkBBAD19+UC9/z99PvuBwYQ/P/+B/UM9wYFDw7wCgn29/gA/AYI9//0/vb//AEADgYMBvr9+fMHBwIO/fb3+f4CAQn8Af8ABAP+8Qr48wD5APv3CPn9Cf4B+QL2AAMBB/T+/Az8/wUMAf3qB/z7/wn9CA3+/Ab/BwH1DAQM9fMA9/0DBwD1D/v0A/UB/vz8BxIG+P0E6wj++wACCQb6BAoE6Pz6/wL4Au8AB/oAAwD8+vz5/QgA9vMADQME/QEDCg0BCP0DDxfy/gMN8/75+/r78Ar8AAIH+BkECAQI/P0L/uv8AQj4Bwb18AT9Cwb8BwXy+fv/8QX49/369/sH8vzm+gMGAwQC/PT/9/oB7PoBD/8ZCPj9DQYO/gsM7vn5+Pv8/gD0+P8G8AME9wL2AvcLCAUQ//v9/gn8DQH///3//ATzAwACB/wF//3+AQv8+gMHAP78/QP3CPsF+wkI+Qzz/Q4D/AMLAAH3/AQABwb/BwoLCvn99fX49f78BgT9/vj+/wX+9QUF9wj+/wL89wYK+wMI/wACAfj//wj4A/4EAAb9+gUK7wD38wD69f7+Cvb/+f0FA/T4BQP9BwL+BgMEDgH/AhUFBP/+B/Xx6QH89f8FBAD7/QEF//7zBQAEAPUBDAkK/wAGCwDw9Ar/6vz2/gPw/QL6BggHA/4CAwcCCPoLBfD+6wH7+f4ABfAMCwf7Cfn99QL2+gAKDvwGBgYH/AoFAg75A/UK/QbwCwcKAAIC/vsL/gH++fr1APT8A/wJAAUBBQQFAv38+wX0/P4CCPgDAAD3/gn8CP0FBPIM+wX2DwP3AQsGAvX/7/79A/sGAfrzAAMKAfAKEg7+/Pz5+vH+BfQM+gX8/v4CGgIFDQLx//n5BgMI+P3/DPwHBgHr/P/8+gUI/gAEBPoDDvr8/fMLBgP69/sM+QQNAwv8BQP8"],
    ["family-plan","safety","/g8OA//4Bez78e/7A/77CQYGBAkLBAP/7foHA//+AA79DwYB+/f1+fX/A/jwBQID9fsB/w/5+wUAAPoD/gv5Egr+AfID+vQE+QT5Df72/Qn/+wT99AoC+Qj2/vv9//4Q/QYA/Pf3BP/+DgADBAQJBg8J9e4BCPb+9P3/BwH+DgMC+/gG9wEV/Pn99QcPDf389gUNBAX+AgTz/wTxAwkDAPsH+v0G8wUB/Av/CP77+xIG+/wE+vr+/wMDBfsBAQL38Af7/P/8A/oF/gH8CfoGBA78+RUE9PsDAv/4/PgR7vf89fsNC/r7CgP5AQP0/AUFBQEK8wH6A/P98Av7DgX4Bf0BF+8DCAn9//gA+vb6+wH5BfAABwgD//rrAwMBCf7/ARv8CvP/9Pv8FQ788Pj5AvsDBwwGC/0IBv39CvoJ9Av99/3x+QAB9QD9BhMDBAMD+wYL/O0L+/4D+QAM/vvxBf/+BPj76wgA+gMEBPb/AQ/2/wL2AAP1A/L+8AgV+QUMBAf19/4KAPH4B/b1Bv0C9fz7BvMH8wb9+gMB+QYBBvUDBPn7Agf79wEC/wADAwAGBgH3DAUG/QP9CP0B9wkFB/f89w37BvkA/fkJ+AT+//UDBPsB/vz6/RIM+QoGBff9AvDzAw73/PwG+QD9AAUI/fYJBvkKAf/4BAX9/QH8AwX/Fg//BQAPBPv0+O7pBfYF+wAH/v0RDP/1/wsF/Q/89v0BBQX6A/H9BgIABvj7+PwBCvcL/f7y+en69v/8BvgTBA0O+fnu8fP/BvQDAgkM/wH3D/HxAgYA9v/69PELCAP///cF/wP2/wED/QAHDAQHAwP6/gALAgkBBvf/+wMJAP4H7wX/CvX6//kGBfYCBAUF//r8BwT5CPr69OsJ+wUKAP78AvsD/u4BBuoJAw0K/Qf8APf7+v0P//8E9vwJAQMB//wA+QUI/Pr09/sH//r8/Pj+B/z8+gUEBAD++wD9CPwEAvH5AAD/Bv8BBQf99P3+CwX+APz8+wEL//YCDwUM"],
    ["disaster-recovery","safety","8gkdAwD9+fn+7vX4APUDDgYL9goG/gAA6vkGB/4F/gj7DgkNB/j/8wEBBfn6Avbx9gv8Awb9/PsA/voM+wQKARH3/f//+fYF/Av8B/P/BQQBAfj/+QwO+gv6BgD/Bv0G9gv/+ej58vn6/g4CDf4AARAB8wIB+/r9+gHvCv77Bff2+ff9+foF/PwJ+vb/B/v5BQf6Ef35Avn6AP71CQH+/gQJ/AUF9gX3//sCAvz2AA3/9vUGAQX/APT/BQT8FgL99Qj09fj///r9AQf9AgUFAAD+8wsD9AMADQ0EB/0I7v0C+AAHDfb2Bv33+AQEAAL4Cf8A9QfyBv3/8vz5BwX7AOoIDRIA+/37APno+PT6//sDAP4AA/v/A//+AwkHBP35/ggNDPUEDvwPBAH/+gT3/fz/9AL/+AP6AQP5AvkF+w0K+f0BDvYI+AUMDPr88vUC9wUH9/n69gMCAgP97fv/BPAF7AL38QcC+f71+PgD7wn7AwX+7g/9/vIB7gAB/vwMBPv+9QYMCQL7/QIABPr8+wsDB/76Af8FBQED/AcD/ucC/QEAAvsBAwUG+Pfw9gMACfX+BgoBBAgAAwT2BwgJAwTzBvP/+QD0AP8C/vINEAAI//z78fz9DAf0APr5+gH6EvT7DfkABf7zC//+/Pv1Bvnz/QQJCQT2+AQGA/IABQL2BgkIB/sBAAHs7/UG+gsNAf3+9wIE/vb5CAoK/wT3CQwN/wELBAjw9+0L/wP1+wDyA/AH+vz7+gIKBAAICQQO//D++v39D/wIBwMD8Az4B/L/FAX4BwL0Bv4J9gMFCAn3AwgC+QX9Bf7wAgYMBf8M+fYP/vwJ+gAABfXt9gX7+gAIC/0DAPr8/QgC+vz7+/b6+f4H+/z8/A399+cI/fD+AgoCBgUCBvYNAwAG/fwK7//2BwYH+gEECQsHBxAHBAgCAAf88v/z/wX9+/79Agv3A/4D8wj8BgQNDAUC+Pv6BPgM/QUA+gICA+/7BQn/9QLz////Bf8E/fv5/QcKAAD7"],
    ["hazardous-spill","safety","+BP4FPj08wQF/+wI/wcKEwoEAxAN9gb/A/oI/P7pCfn6DAIA9QsA/+/2Evz1DBEHAAD//f708v0GEQ/69gf8BgUDAAv27vcI/Qz8/PoGAgj2+gz9Cf///voE9AHz+wH4EwL99f3/+woGAO4GBQjyAAMB+QwKBAz4+fcBBvsC+P/9CP0G+fwH/AUEDQ0L/gAB+Az6Ag8E9AAA/f//A/8HAgUGAgUN+AEKAQMC9Pz8DAL9C/4G///5+fz7Ffb8BAgH+AL1/AT8AwcD/wD5/AwAAgkDA/4EAwUD+gL7BPwD+/0G9fIE/vYGAf4A/vX7+f//BwcNAwT9Bgr7/vz99P4E9+0I/gvxAvvyBPX38/kT+ggL9/cI+v0E/wXrBPX19hv2/v4AHvv+Dw38DQQH8QgK/AUAAvgF+u7wCxEK+//2/QEB+O7//fYI/wEM9gD6//4H6/cGBwIEDvMF+QX3/v4H/AQKBvMFAv0E/vT///gF9f/8AAEFEBr49ggAAPn9Afv4+A3+BP31BwL3Av/8DAkFBvUK+QEMAgH7+wIF/vsAA/oA/AYDB/8A//YA/vwAEAD/BgMFBAf5AwD/+QL9/v4IDvz9APH++gb6Bvz4BAEAAQQEAg4B/gUABu/8+fwC//v+/QH5Avn5CQQD+/0C/AAABv72+f8EC/T8+gT+//4FCAXvDgoU8vD4A/v18fzzCggK9wH9Cw0CCPkHAPkEAfEAE/kFEgTqAwn/AO8N8+//+PzyAf4A//8B9BP8B/jy8vsREwMD+QH6APX+CQf88QoABgzz/gP+/Ar6B/0B/fwB/AMK/wL7Bfv49gUC/fb+CP0UAwP7+/r1//v3A/n7CfIBBPsP+gT4+QLy/f4AAgUACPr+/gEJ/wz3/P3/APgH/ffsAgUL/QUEAfkGBAAFBgIMBQH+9g37+wANAwkG9wn+/wf/CAUFAfsEAwQE/vv8Bfv4BPnvCvr6+QQDDwP+C/39CQz+/gUG+AL+//729/fzAgUBAAj4AQEF+v8E/fn9Bgv8"],
    ["fire-extinguisher","safety","/wEEFf/6BgYX7gLuBQkJAAoOBA0X/A0A7Ajr+P3y/gQA/f4GAvTv8wINAvMD/fUF8vYDD/kA/AD9BgP4CwEE+AAF+AAF6v3++wr1Cv8UA/IDBQDw+QL+CP3+/gf39gYHAvr+AP77BvsBBvoE+vcAAfUIBvwNDg8D/AT9+/T7AP/6AAgK+fz+B/zs/gf9BQEIDPMI/Qv8AvgC8foIBvn2C/cABhADBA4E/AACBw4IAQQIA/j+/g4E/AEE/PoL+wYK+AT3+vkECfv7+/sCA/0CBhMDA/n+/vsAAAH7BQcC+QAB+Pv7AgECAQQBBwH8/AQEAf8CBPkABwUI+fn/BQHsAPIFDB4B+QEFC+/58QYFCfsJCggIFf4F/uwI6v3/7gMAAv4OBf4E9/H+DAD0AQX3CPX4BQz8/vf5+P8B/AwDBAUF//r5AfgHAQAQ8A8CDgH/AwX++gYA+AsH+AwI9fgGBv/1AfoA/f/1CA/1/wj7BA74+vwA/w4SBfwE+f3z+///+voHBgQB+wH78v4F+QMFCw74CvgJA/j/BPT8/gn79PzyA/8KCQD8/gMK9gIPAwgDCgT5Bf4EBfsCBQX7BvgEA/4J/Pf1+Az6A/75Bf4NCgIO/Pz89fj5Av78AP8A/vkHCO4C/fv//gcD/QUB9vz8A/wB+vwABAoN9/X/+gAJ+Av7BAkQBfgF/w/x+/AEBAwBBAwJChYBDfvrCun3+vAAAf/9BAb/+vT0AA8D7fcE8ATw9wUR9P38+PoHAvYLAgL+AAP4AAPz/Pz4CfIG+xkC/AQA/f78BQAJDvsIDPH9Bgn3APsCBPb/8f0N/gL/8w4J9/7+AQcMDf3/Bv73+PsCAvgEBQT8AfwF/vUCC/cBBAYM+Af+CgED/QP4+f0C/ewC+gIFDAb5C/sCAv4CDgoICAgD+QX+BwIBAgr++P/yBwj8CPf38vsJ/P38+QUC/wsJEAP5/fv3AvwAAgEIBwj6BAD6AAD+9/8DCAD++gP3AwMCBAX8/AIIEAD7+fgJBPUE"],
    ["mass-casualty","safety","BAoYBQbwAvwD6/YHAgT/AgYGCw79ARL67/oH/P36/gf9AAgABvXz9wr7DAP7/wD26A75BQb7AAn9CPz8+gfzFRH9BggG9e0D/gT3AfTxBQ0D9PX09w/2+gP8COkB9QkB/wf59Pb2+/7wBv8M/QUH+BMK/fsH+v/1+gT3BfrxCfgB+vT7/f0MB/799/3+A/wFBQX8DwYBAP3/+v39B/4DAgcD9goB+w37+AgADQX8+hIC+fQG/AEDAvcDBwP2/QQE8QP89gT9A/gA+vkC+wkIDAYEAwoE/QIBBAABAPcF9/0F/AcDBvn5AP0A/v8B+QcDAwEG/v7xBAMG+vz3BwcHAPwRDgkL+Qb9BQL5+ggE+wEJ/PsD+wP/+fr9BQsD/f/7DAEHA/4KA/j1Bfr6AAr/DPkKBP0G+wIP+AED9//77AMF9vz1+v34+PT4BAD/AgcA8gwAAuf99wALCAQF+gP0DAn5+/oF8gb6/vcDBAkG9QkCA/zt+A4CDvQB9QIJAwD4Dgb8/v4A+vr8CAkAA/X5+Qr/Afr+BP8H+wX7Awn5AvL+CwLy/vH/9AP++QT6+foT/vn3/A76CPz5AP/6BfgB8vEB/Av9BP799PQLAvoGBwECCuYNA/j67/8C/f8ABPAH/vD58P73BP/+DAwGBP4G/AYPDAP59gH++wYGBv4A+xP4/RMRAvP6/ADt9gMF+PT7/wMIAQIIBP/9+wADAfcADwwKAw38+/b4+QD69foDAgfq/wH2DwQDBAMIA/n4A+8PEf8A6/v57Qj7BvwBA/wICvr7AfTw9u4JBv8K/QX2A/8GAgH3BPMD+PP4/QsAAfcDCgb3/wEMBAX7APAG//sJ9P/2/f75BP4A+/j1AgAMAQIFBQEH+QX9/fH5//4M+wT0+wP6BQT8BP/4Af8QA/r8Fvz3/gH6AP39+wcK/vT//vftDPQF/u4C8/v4+gQHBQQGBQMGDQT5/P4ABPX7AAfq+wj7//8J+PUC+/kGAPr/BPoKBw3z+QAB9/n+AfgM+wEF"],
    ["heating-outage","safety","8wMKBgEF//b/9u/07vcMBv4I/fYBDw0J6QEF8ggG+/39DQgBBAkEAvoHAQD7/u3++/H8/w/5C/4EAPUQ+wUF/fX7APj98gLtBwH4DAj/Afv9+gsC/fwFBQUBBv4MBwH+9wAC+fv+BPsHBwsEDfr/9gMFDRUG9gv7CP8DGfwVAfYPAAL/BQX8/AoGBvX/BQH9CQAA+voMBPj2/gv3EwD6AwwB//b8BAIQ+vX4BPf6++z4AfYBAQj9CAT2AwEABfcE/fkEAfj9+AIHBvsICQD4BQTzBQcGB/v+CAcCCwP6/Pb7Bf7/+wH7Cwb4/Af1DPX+BBEH+QcC+wj8+f/5+gABAvQJDBn7/gH2/vXi9ewKCP78/gv8AwIHAOj09/MA+PkIAvwTBwwH+gf6/xIGAwLwBf0B/A8O+Qj7/A0BEgb/CPn29foEB/L3/P0H6v4H+AAGEP7+A/n28gTyCfr8AAz7AfML9Qr7/v/9A/wDB/4CAQIF//oOCfj69wz8DQT8BQQABQQD/wMMDgf8DPkAAPry9P4AAfoBBggFCP4F/v8CAgEKBvn+BQsCAAL59PcJ8/38/AH6AQQDCP0FCQYDAQgC/f35DAQD/gn+Av0L/PoIB/kK9P0CAQ75AwYCBwUABPb5BAf2B/33/f0DAvsI9AT5/P//CvwG+QP6+f7yBf/5A/zzDgoQ/v8CBwnr7/b99gL8+/sD9gIBAgz1APwHBfn+8PoJBxEHCvgC/QkK+/gF7QEBCPkHAfwD+P/s+Qr8BfH7Cur59/bzAv36Cf8FCgMFBf32Awv1+/8KAP7+DAEGAAb9B/oEBvIJ//z1Bu4ACvgQBf79Bv8JAwLr8voJ9goDAv/29fj+Bfn9BvwB8QP4+vwKAgkH/AQA/PX4Bfz/Avzq/ggBAQHx/fgB//T58/wDDQL5/AD2BgEI+QgH9g0I+vkA+vv/AwIG9PcC+/4BCP4C/fvvBvn2AAsECwn6+/gABAL9//kI+wAL9gL5//z79QkABf/uBwYG8v//Cgj5/QD/"],
    ["anaphylaxis-signs","health","7vfzA//uDAr68fQJ+RQF+BL6DPwLAvvg+/wKE/v2/AUKAvsC+voCAv8C+wP4+wsHFwTzBAT19fcBCwXzBvQADvj5/wYN9vTlBPkA/P4E7PsDBf8NCgH57gP6BAIGCAMABxMIBgj58wUCCAjpCwkP+/wJ+wD2BAf+/goB+/X/DPcPA/kGBPv7AP37Af75DgMJ+AH+A/kBAAIACAwBD/X6FAAF+Q0EBgIC+gH7/P8EAv0A+gQB//7/BQII//0DAQf/AfoA/gUBBv7+C/0C/v35APsACgED/wT/Awj7Bf0BDf/9/QUGCAD7AP7/+wQJCQYBAwD5/QICAvz//fn+AgYBCfLu/gTw6Q4FBe7k/P/+CPwC8AP7BgL8+/IS/AIKA/j7EfoH/wP0CQEIBAQHAQkEGAACAf4NBfQI9fwF9gH8/wULCgbxCBEBAPv36Qn6BeoB/wHtAgT/9vELCQ39DP8HB/8O/QT++wkCBP8GA/P9+wr2/fH48gAA//oF9wn/9fn6BAH8+AIGAf3vB/b+CwwCBPb5AAv7//39CQID+wf7AgH2BxH4AQEFBgj++gL+BfwAAAMDBwn7AQMA+AMF/gEA7gL/BwD8Awz18gMG/AH5AvsIBAQB/v//+f8E/vv5B//4AwIEBAkAAv30AA0FCgX+9/r3/AQHAwL9+vr4C/76AgT29uwR/Oz7Eer9/QYDCQT6/vEQ+QIH8u4NAA0P9PP5+PfxBQX7BP32/Av4/gD9DfwV/+wLDfz4AQsF7fH49Af99QAIBw0B9wEJAQT8+gTy+P8H/QrwCAAG+Qj78/7u+/wLDAAF//73DAAG+wX9BQ0BBwf36wAF/v/79/wF9AIC/wr/AA0EBPwF/gUBBAMDBgb+/v4ECgAGBvv5AwIFCgQAAvwF9wcDAwb0+wMD9AEI+PYD+wcM/QcC+f8G9wsB/v36/wMG/f0P/AYD+AQA/gYH/wkPBAP+B/8CAAH9BAUD/QMF+wMD9//1+/P6CQP8DAUB/vjwBwgBBgH6+/0B/fkM"],
    ["electric-injury","health","6gT/Ifr5AAv++gf9CP/+BwAFC/QGEvjw9/37+voT/fv4AO31BgACAPAECwoGA/gC+gLvCPn0Bw8FA/T/BQLxAA4ECAnxAQPvDAUA7O34CQnx8f73Bf0E+f/7+/4GBgcEBA/7+/j3CAAKBQcKCQAH9QUHBAME9AoBCPsHCAD9CfsG+wEC/gYEBw36B/r9Cwn1A/T98/77EgMIBf76AAL3AgAA/w35+QkH/ff/Af4A8f/+APkG8gAEAfr+B/4C/fYE+gUABv0B8wH6BPsF+AX+CgEF9gYJ+gb7/xD4BfkKAP/8AwMD+wMECQgEAgYI/voC+QMGAg/99f0EAAME/ggFEOgD/gYA9fr98Pb0Dfn/9PQCCgMA+REOEQf7AP74DPIA+/wOCQz/BhEM+eIB+gMN/vz1BgQA/PIKDAn5CQIA+wIG+Qb8A/j8BPr+Bgj79RL98AMC8vgCAAD5AwD7+wn6/f4LAgr3DQ4D/Bb+Bwj9/gH6AQ4DE/r/+/cJ/AX88/oNAgH+BfoLAAUF/v8E/xQG9vn9DfMJ/QwAAgX67vf98wQIBwQGAv0D/w34Cw32+QUDAPj9/QAJ+wQJ/g0IBfgEB/7/CgUC/vzyBAL4BPz8+AQJCQH8AvwDAgX7AAQD+Qr8AwH5APcF+wUC9v39+/r5AQYI9/8D/AAED/T8Awf+/v3oHQMTEf70APMFAgj//ggLEgwN7wYI+QT79wT7Bwj4/u7/DPf8+gECBwoEDAf7AQL99gIG//P8+wj/+g/y+/IGD//6/vr6+AMBAvX8D/kIBAAACAP1BwD5Bv4HBgkA8fv9CAcA7wEKAQ8LCwwIAP4MAfwI/P0A/v8FCfb58vYFCwgA+/8N9wD9+Aj2BAYAAfgCAQb49gL+/vz5BfX//voNB/8N/AQHCQL1AfcCCf4FDvj8//n8Af4E+QAKCP0E+/n8BAf8+/wD9P/+Avn+/wUDBgz9AgD5AvgJ/vX8+fz9/AwA/gb4+gMFAwUABwPzBgryCPkNDPwE9P3w/vwL+u4J"],
    ["poison-ingestion","health","3v7zCvPw7hQH+uv8/gr7EQgJBRD++gL6/wAB+wXz+wgIAgAC+wMXD/T3/PQL/P76Afb7/f/4/PAQEgT19v8B/AcL+wcB9vz/9////AYF9QUB9wYI/wsG/Qf3BfgN/f/9Dwj7+PsJAvn+/AIS+gny+/r9Bf8ABAjyC/n/+fv6Afz8Bv4J+gMF/fYBAwILAwP6/wv2CQr9/wr8/QILBv71CAcEBBL9/vr+BPf4BPf8BAIGAPoAAv72+gH5CvoN9fIM/f/5+wT//vv7EfrwAP0EAgj7DAQD+P8G+Qn+BfcFCPj7AAL2/gD+AwT/9Qf+9/X8/wQFCgMCCAME/AD0/Pj9AOv8+wXu8PsDAQgA7f0B8wr3BfX1AhEB8wj2AwXyA/v4AQ0E/P30Bvf5AAwD7v/2+PIF+wf5//MGAQ0N+f/y/QcFCvr3B/MD6RcI+f0AA/IH+fn+9PEVCQgECvcH//r2AQz5A/AF7gD69QT8BQr3+gkCBQT8AQL+/QH5/PUGAPL0/wAEAf0DAAT+BA3+A/8LDfT5EQcGAf34+/cE8/kI/fwABQQACP3/CfYCAf35/QHzAvn3BP/9/Aj9AAb+AwABDv38BAD/BvwF//QJ+v0FAPz5DQP7BP37BfoLB/0FCPoAAvH7AwMC/QcEBPrvBv8H/P/8BgUBCvn3Bfz3/f4C/fDx/PYD8eYEAAr/9/LsARAICf8G8fQBBQUDHgUB9//17Qr9CAHtAwkB+wQQCQMABQwDFvzyBPn/+QP/BwP19QP/AAgECAkDCgH8CPwJCf35/wn89wwGCAAIAgYB/gX+AP4QCAf3+/kE9fgH9/4EDwQH9QYL/vz9BwkC9fX6+wv9APv8BAYL+vIC/QASDAUDBQP3EgQJAA34B/797gEB/f4FAwcIC/wBBf7/FPUKAggHAwEABQMK+wIC9vn++/0HAwINDAcGAwL7Cfr//gIGCwMB/vX9BP8GAvn2/vkF+gD5/gIICAH48PsGAfwH/wgK/PYK+wQCBPr6AAQA+fr6+gcB"],
    ["food-safety","safety","6/YPAPDyAAQH+fnn/vsICPr3+O0ADfj9Af74BAz8AgwT+w7/+Ab4DgwDA/71/u0F+fX7DgP3BwT9DfkDAPfyAQH39/r/AwP59A73/gYGBP4E+wQA+AfwEQb7CQUGCwYS+ALy+v7u/+74+QICBQIDDg0D9gv8APwBBfj0D/j9BgYAAf79+A/9CgMABQEI+wsC/OwOCf33//8FAwn+C//1+f0BBf4IBQEED/sD+/0DAPgDAQL1BAL/CQYB/fgH/f3++wYHBgf+A/oB/wQC/AUDBPP0Aw/59/T7Cw4AA/ID+gEB+QIDDvnz+vwABAAA+/kCAgL/9vz+BP77BA0BAAL5BPDyBwbz6AEL9Av28PwF7Af37Pj9+gz99gMNDQUI//sD/wD3/PkB+gr2AgwaAAj4/Qj3+QAA/AkO9AgD9f0F/vwTAvf7EQAB/QL8//cE/gMB9wv6CfkH/PwG9Qv9/vkJAAgH8vr09v39+fsIBfEA9v0U+gD/BQD59gIA/AP6+AP9AgHw/fUIBQT2BvsM/AMDAvT8AxEDBv71CgP9+wX8/wb+BBMG+fUF/P76/gb9++3+DP7//Qn8AwX++gAEAgP5Bv8D+g4J/vz3AQIB+P0CA//88AgJCQAE/QoMABDzBAj7BQUACAn++gEACf4CBv0E/ATx+wcC//74/f0CBwEUB/viAhQC8On2CgES7ewBA/kRAf708f4SAwcGDfb+CgL+Fgv/D/73FPkIBgj+DfMHAgD79gX9/QP+AP0JAgT9AfIFCgL8+gAMBv78//38B/T8/v4KAgL6A/kKFOwM/AQCCw//8/vvBfL7/Aj+8wL9APj/DPH8C/0G+/wAAvUM/P4D/wH/AAP2/QMG6P7++gACBPsB+Qz+BPn2+QMGBvcJ/ff6+AMGDAcG+ggF//0D/gX89woD+AAA/QYH/f0I/Qf6AAsNDP0FBPkD+QIA+/4BCf8E/PoCBP38BQQIBAsC8gH8AQMDBv4DAPwABgr+Bf3++/0AAPzyAv0HAPz+BQX+BAIF"],
    ["breathing-difficulty","health","AQ4BGf/1Bv8B5/AKARHt+vkJ+fsK//gMBAsMBPb0+gYF8/0EAf8H/wQYAPwCCgb//vUCCAsJA/349gPzBQsIB/8AAQED/Ab/+f7z/gkG6v/2Bv8G9RP7+QkA+QoP7gIDBPPsCg4ACvIE9A0HBvrxAe8I9ff3Av30/wcNAQf7BQj3CgT0BPn0BPUCAAMDBfv2BAMCAwMA9QL39AX69QcJAAMCBgD8/wz9APn8Bv0P9//7+/4DAP36BPzw/QX2+PsCBQoEAP37APsB/v/8APgDCwQIBgYLAQT6/AT+AwD3+AAD//gABQDx/AAB+QL2APr9AwABCQADBvwE+/YLBQkDCP4F8gEF8QQB/uzxAAUI9f4BCfoCBv35CQH5AwUDBvwHB/L2/gf2EA33FP79/Aj8/gr1AAH+Dvf8DAAU//gF/gQIBgMGCAH9/gkD8/79Avn8/xrvE/kF9gP9/ggHCPkKAAEB/PoK9f7y/wQMA/gFCPYM//AH+gYI+QQC/P0RAAH+9vUH8wUF+Qb0+gX/BAwK9/wFAfwE9/wMC/v59v4FCgsECgADBP4DAQn8AwoGCvH9//T6DAQKBf/39gYN7//1Av/4/Pv18v0I/v78/QD+/Q0N+AARBgUJBAD6+gwABfgAAwgBB/cI+wgN/wkD+/n/AgL8CQwH+v4D+/wMB/sP+Q7s8fH98/0I/wPu6vPzBwz1AQYKABD6/f8B/BAKAP39Afb+AAEQ/fwIBPTx9wH7+AkJBP0GBQQB/P8TDPYJ7gcAAP//+RHx9fwFBPz+BQnxAAgB+wTxBgTw9wv1+wr+/P0ABf4CDvfr//gA+uf2AA3zAwgC/hcA+wcGAvz5AAkH9AX99AAF//0H+Pv5/wL/+Q4FAfsJBAb8+wD8+/8F9wMKAgn9BfYMAwcHBwP/+Qb49wD+/PcBAAUT/f4FCQcGBgD/+wT/AP8B/gb7BAT/8AP6+wwCCPoB/v70CAEC+vsI/fgK/wQLCQL5/v3/AAP8CfkG/gH/AgUK8gkB+AcG/O8D"],
    ["altered-mental-status","health","7gv2/PX6DP8D9gH2Awb5/AP9APT/8QIM//wK/PML//70AAcS8wAM8gH5BAv++Qb9BwkJ8/4C9/UFBQAJCPgHBAoJ+wAL8v/0A//5Bf/5ARHr9fD/9fkF8/38//kG/wEBBAMA+ff6CAL4//v6Afr8Bgr09gH5+PYK9gX5CQ3///oG/ggDBhENDP/+BvkKA/wR8AD1/AL8AP8I9/kD/PwFBPv5+QX6/A/6+AT8+wMGCfQB/QkHAPYB+v4ECf39BQ8I+/v+5/7/A/fxCQgFDP8L+v8PCwr8Cf0E8fD//QD+9vQCCvr/8fwGBvj+/P4CA/XxA/v8/fb7BvX8AAL5/gj9B+gB8QABAwf5DvwQ//cLC+v9BfoAAxD5BAUBARD7+wgE9vvyBu34Awz/BPkK+w8G8wnx/fb0//UJAwf0+vMFBAb4/Pv2AAH8+wcFAvf39QL5/P8C/gIB8A77AvgJAwT8/vwA+P7++gEG/wH79/bz8/z2+Pz66wgI9vwKBPTzBusH/wcAB/z6Bf/5/gQHAgcPDPoA/AIEAQT7/vMG/AIACvwF8gHyDQr+DwT6BAAG/P38APoHAxL5/QMC//38APoR+/X2+/IK9QII/fUKBv/zC//7BwUD8wH99/f+Av4B//3/DPz19AIJ9wT7APwD+PgE/Pv8/f78Ev0BAgYE+PX/CAPwEP0DB/gTB/Pv8wbvCQX87/v+9wECBfXzAv0LBwL/Avn2CQYHAwkEDf0JAfz39Pz7E/sF9AcK/f3v9QMPB/4ABf78CPv0CvkFBRP///f6CgAFB/vs/QrzCggF+/wCAQYC9vUM+QEI//35/wb1Bf8SC/v5AQEG+RQBBAX8CQ779gv8+QAJ+QILAf32BwPy+gEJCv4A7wEABQD6FAgG/gT0BwT0AP7+CPX+9wb0Av4D9Af89v0DBf78BPUH//sDCAwD9QwB/PX4AAYG/AT79PwE/Qr6AgwG/f34AgP4AQcB+wMC+/IH/Ar8AP8BBAH2+/wB+QIEAwwC7xP++gMEAfkB"],
    ["smoke-inhalation","health","+foADfvtBAb9+fYIAhz0+v8I/QkLCfT6+PUFC/n+5QECAv0RAwoDChAS/QT6/QcA+PfyAv0TAPYKAgD4/QQAEPMG/QAB9/T6Cvj+CPwO9AP7DQMLAQn08AMBBQUM9wH0Dwjz/gz+Bfb++hX2DvsC+v0I/vj1Bg//BQr1+wAGBfH/A/8G/P3zBfUI9wH3C/j/+AQEDf76AP72BAL9+w0ICgD9CPv9BwX5/f78+v0K+vT+8wMCAgcHBff+/AP49AjzAQED/AP7Dvv6CAL+/P0D/gL8DQMDBQEE/P/+APkDCv7++gMFBgb0CvsE9QEEBv8D/wL3DQIDBfwDBfYA/AsHAwHrAQL/8Oz2BvUC/wYGCgIMC/gRG/cJBvMJ+fkK+P3xBfMIAPoFDQkK/QX/7B71BAIGAwoECAECBgIU8gwR+P/3//UID/79D//8+AMBD+z+B/f8/gf//uwCBP3+DwIE8Pz78/v2AAMB+woJ9gwMCP8ACP3+AwQG/f4J/f4C8gv4/ggDAgL+Bv/4BPYC+g3xBQQBDwT8//33+/j+APsJ/wP89gMI+wMDAwIN+goACAYJ/P3//f0FAwYHBPoC+vn/BPb6/gED+gQB+wD8AwYDAfgGAwMDAP799fYEAAf0AgL5BAT2Av78AQMLCvcC/v0GAv78A/f49QcC/gf/9QAL+gfq9P4M+ub+Afjw4v4CBwUB/xH8BAv9BQn7AgMECf///Arz7f8J+v7/EQv3+QAC9wwC9/wNBg/w9hH8CfwEBvsC+gMGBRD3/f4D/+4WBQnmBgUC9gMICffyCwcKBg3+BPwKCPP+EAL5BfwFDAUEAAr8+AD/9fYJCfUAC/L7AvgK7P0F/PwH/fQH9gD6A/4H+Qr7AwIQBgH5/v0A+QX6CwUM/P4IAwYCBQH5BvkBAgr59vz99vv+CwwF/fj7+/77APb9/vr6+AAAAv0B/AMD+AMBAg8H/gP//gX+AP37+wX+Av8KAgcADP8AAgb7/AABA///AP7+BQH+Bgf4+v8DB/sJ"],
    ["childhood-pneumonia","health","+fgECvLz+QH5/Pr/BwXu/AAPAP3/Cez3BfMOFur57AEDFAAE//cD/xAG/v8DAOoJ7P/6CPUGAwH/Avf3+f36CAT5BvkE9QH/CQDuCAUL7/HzDgsD/hL+9v4ABgUK8QIKEAbz//37Af8E9P/+Bvb8A/0GEv35DQIF/vYHAwEG+v8ABgT5AvwCDPwD9Qn/Bfv7/PsECP/5//j09wgB9BQFAAAABgIFAgwDAvL6//UL/Pz6AvoLAgkDAPUEAQz/+QcGCfkHAwD6/wIH/QICAfgABvwOAwEJCQQA/wMF+/wK/gH4+gD5DwT9AAII9fv6+/35/wr+A/4E+/oN/foC/w76APr98gbx/gcHAPnuBvkFAf3sCgD4+/8H/AL5CQrv//n4CwAJBwMD9AoDAfr5BPsB8+/8+QQBBfgE+P8I+AYG/wYG+AP/D/cF/fYF9QQB++n2BwEC9wQIEv0H+gsNDd/y+voB9PkF8Qn7//8B/vz4/vn2DPf4+gP/9A4ADwH99fsP+AD//AEE+g7/CwD8BgP1+vj2CQP9+vYD7e4BBPsP9wD1/QsA/P4G/P3+9QT4FP75/wj8Bf8E/gL5/fcC/PgDEvsNEAL8AP/1/foABgL2/gsEBwj9/wL5+v8C+gQD/APzCf4B/QYE+AH8A/D2/QL6AAb/AQgCCAMFAAv2+//7/AIC+/sQ+vD9C/ED+gMCFgP7+gf5AwEF/AX7+RD+9On0DgcGDQwC+wIFEwwC+/8J9vHyBP8I9w0EAfkI9voCCAoD+/L9+gDwAwMC/AEABAfvCO8BAA32CfXtAQQJ/BD6CP0IAu8CDAAGBgj9CfsECP/48QQGBQMGGvoJ/AUFAQMIDRIGAff4/vsE8wz/BQEG+wX+/v4IAgkCBvbt/wD/GA4GBgD89fYK/wMEBgf+/Aj1+fv6/gX4Af4C+PoHBvwDBPwK+gn5/fL49/3/A/77BwX/DAIHABAMAf7++/z7+wUHAv/9+gQB9PsDAvn5/PYE/AH5Af7+//8H/v8DAAcEAAUB"],
    ["diarrhea-disentery","health","+/b1/vDdDRL7Agfu9fv7APcE8Q8E6wT7Ff8ACwMC8gD/AwAEBQL8EPn3+/UK4vnr+wL/9fcG/Qj9BAX8/Qn3FA0G+Pn9AQQAAQoH/AgL+/z1/wz2AgoD9Q4CAPf+BPDuDAr8BPr3BPv68gsD+vr9APwFAQD4//YKCPP97vID/vj//AcG/f4DAPgL/gD9/gP/8vMMDv/9BPj/Bfr//f/3APf9AQAE+PUB9v77BvQJBPcC+AAC+QQH/vb9BAD9+gUQ/fsF/v7/AP4E+v/9AwH/AvYBAggGB/0BAw0KAQAC+AcCAQD+AAAB+/v6+v3//Qb9/vcABf0HAwD8Cff/Agj/+vjt/Q788wD57ALw7fX69wPu//4B8/Xv9fwH+BX6A/73AgH5Avz96xL5/AUBEvX9/gsC9/by+O/3+//3CAL97P0NB/78+/wGAQkK/fQAAPf09//+Agj+BQn+AvkC/gT/BAX6Aw8J//gG9wka8/b/+gUJAvMB9/ryAAn9AgX5BwL+8PoJAgz7B/YACP4PCwMG/fz8Agj5BwT+BAz+AwQA+g8CBQsFCAL8B/UAAg39BAX4BQEA+gQDBv0A/AX+BAX8+wv2CgX6Af/4Cgv9BPr7+/73/QwO+wcEAP4FDAIJBv8A/gEG+gH7Bv8B9AAO/QUPAQT7AQYEBQn5/P0J/PwJ/wr5/P0R++EQ/gH3+Or1+gsJ/fYB/wLwB/oSCQoHCPn5CPcC/gr4D/cB8PX//wfuAeID8/vsAPv3Cf0GAQn9Cv0ICgb0+wMECgj8AQQCDAUAA/gRCPf+BQH7DP4A+/oD9PIEBvIF+uoTBfPzCAXxAPoEAQb6/foB9wn+Af/5+AD5AgX7//8FCAL9BAb9BQUHBfv4/QQFBAL8BfoN/QME+f/39PT+A/r5+wf7AQEC+QACAgMJ+P0BBQXy/PgH+gz4Ag76BPoG//kC/w8C+/wEAgEL/vcND/gL+PoCDQIF/vkAAgMBAAP3AAH//AD7DPr8Agb7+vwIBwz/A/8G+gL+BAMB"],
    ["prolapsed-cord","health","9v4ABvr7//37+vL9/Pr1Af4P//QH/vsFAvMGCe0A7f38Bgf79vn+Ef0C9gf++gILDPP1/Pry7voK/QH5Bfr2ChAF+e719vsIBPz68/wECPz9+AICA/YH/AMC9f4DB/D5AQz2+xAEBg/59/39/QEIE/gEAwX4DwH7/wLyDvr9/f38AwT4/Qn3BRIO/gABAwUC8gcDAPv+Af8CA//8/g33/vwADg0MBwn///sEBwD6BvsGBAIEBwX//AQGDQ0FAQT3/gcI9ffzAf73BQMGCwkN/hEB+wABDgQFAPT7BPv6BPAF+gYF/QX9A+79APr/D//3/Qj4CAz/DAQA8vcA6/gA+/X89AT89+rwAQEB9gv68/QFCAUE+fz38f/oDfoH+PHv+gUDCf8E+v/9+f4E/Pn+Cg7/Bf8BA/X4/AX+BAYE4wIYEwnvAwUE+Qn/CPX/Dv/w/O4H+gP5BQfy/AECBQEJAwQBCwUO/AMA+QADDvvzCQcO/vb7BO8F/AcI/gcD+gv9+/MUBAX0Cv0I/P/+BQ4IBAz69Pf2+AcD+wMJBfj7AgQDAAEJ+P4BA/kI/QIA+fb6+AANA/MIBf78Bvz6/gUC/wz2AO799wwCAAL3CQP4/AYM//z7AggJ+wIA/v/6CwUB/g35//z7/P34AQoC/gIB+AT8AggCAwH2Bv0B+/f/Avzy/fsH+fX4Bff+/gf49/b7+Bj3/PkC/Av38AUH8Qnx9vYMCfb8+f0R/foC/wjn8/4HAfz77v/79Arq+/8C/vUFEvsE+AD0+ggMBff3+vsE9QDw9fgC/Az9/AL1AvUH9/wM/vXuEfgB//MBAg0IAgIDBQn+BQQO+v4E+PMEAgAB+wD9AfoEBf3/DAn/+vgIBPr8/f72AP/5BwIB+wX0Ef8CAgILBAYFBP0D8wEE+wf8AQX8AQsJBQII/wcJCgQL9gX2AAn2/fn9Cv//AgYFBgESBgD2/AQBBAAE/PEI+AMC9v/1BQoDAAAA+gX/9Q0L/wIACP0LDgHz+Qf5+Af29v4B"],
    ["severe-fever-pregnancy","health","/O769/T0+/n+8Oj/BR0C7fkB+fb/9gT+/fwB5/L3/v8J+AAFDf7yCwz3CP77A/T48gb++Aj5/P/vAPIQ+hABBf35BP/56woB9/sA/vv3/wgAAf4BAQAFAfwGBAoJAP4Q/wf5+PgD/QX4Bv4C//35Avj+Bgf9BALxCwEDBQYF+/757gb6/ggDAQAK+fcF/f7/BAT3/goOAg75+v0G/QgE+A8DCvQAD/r6C/r/AfcH/QIF9gME9gcH+QP/Bf78/wQMBv8G8QH7/wL++gcRDAr8B/r9CQj+CgcBD/r7C/r+AfYOAAD/9AIHBv4J9wAHCv36/v/49AUEDQYDAgb9AP72+wDq5vX28/sJA/3kCPMGBPb+/fQD9e8N+Qb9BQT6AfAFDvgEEf0E4gf6+vkA+Ab39fkU9QT0CfIB9/v5CwsJ/f0H9/76DfQCBfD+BAf1+vPxAe4A+gP6D//3+/kBBPr9/vsB+P38APn/9wX3//oF+vz8+QICBQQM/AD4CAQE/vsD+PAD//cN/gn5BwX5/QAA/f0B/A38B/cQ/fgHBwML/gACAQUF/Aj5/QkB/P//C/j4BQb9//cDBvoABf/9+v7+BgUJBPUA/wYEAvUEDQoCAAQB+QMB/v0J/wAHAgUEAwn6Dv34Bvn7Dg4EAf36AggA+/YEAgQD/AgKAQgI/Pn69gbq9/UH+PT8BPnt6/7tDvPy+Aj2AvQCCAQCAQv8CgQF+wr3DAkF9/oI9PwKD/b/9P0H8foF/P8JA/f/9gcPAQLzAwsG9gX29/n/CvsMCPz4A/Xw/wH8//X98wb/AAn+AQb7/fgD/wIEDvH7EgcB+P79+/QJCwAMBPwJAvoCA/sI+P/7/gD+BAII/A/78w0A9v/4BvgFCQMHCf79+gQJ/e0FCAYN+AMF/QUO9/4D+QD77/7z+wb1BwAB+wEB/BADCAX+8wUGBgX7B/4AAgYIBf/+/AAIEQQEBgUQAQAAAAL58QsF+Qn1+fn9AAD9Agb/Bf309Qf4Af/9AAb7AAMI9fX+"],
    ["postpartum-mental-health","health","//Ds///0A/wA9PL88fEH/e7/Bvn9CfoC7e0CEP0U8/D8AP7/AP8EDvQD/f0I+AAG/hQGBfgE//D9AgHz7A3/9QP8AAgOBQT/AgAA+/f79/QBAvgDBPP0/fcJ+fX+B/EDA+jy/Q3yBP7yCAgOAvr9AvwBAwv+DQoKAP8JAwIH+gH8AgT7Bgf9+v4BBPsJ9vz7//T/8QH2/P4DAggA8wQO//oCBvwA/gP3B+0E+/b//wEI/wT//An5AgME/gkBDv79AQYB/Ar4AQr7APsKAPr3E//4/PcD/Aj9A/L7AvwW9gYFAwIL/P0D+AoKAPz+APQDAf4JBwED/QD8AgIG/Ab5Bf4B+PrwCgIICfL7Af0L+fv9EvoDBPf5BvX2AhD+DvYAAxD1CfX5AQoF/f4D+Pf1AwH99gj3B/z6Df4B+gDsAQUFCv/3+wTz/fsECP4A+QX0Bf0A8/IADf/6D/UCAgMACf37/v0T8gsJ//n+Cg3tAg36/wz/Dhf0AQoO8gsE/gb58gf5+P0QCQYFD//2/Pr9Cfv5Cv8D/vUJBRD6/wYM+AcF/f/8/gMJBAD8Cgr4AgTwAvj6BQH79v74+QEQAv4GCfwNCvL6A/0CAPgCBAj0/+7+BfwHAQYDBwEL+//+DAD+AQAABfwD//P3CPb5/v0G+gX8/wECCwbzAf77APv7/f8E/PX+Av/sCwDp/vzu/ff4Cgn8+QL4/Pr0Ag0D/v35AwjvBvwLAwEE9Pz/+AAJCf39CP/r/AoIAvIAB/sEC/sD+QEL8/35BgUB/e4AAv79//X7+PkH/vQQ+fv/AgQL+/X8BAQI/PkF+Ajv+Q0JAPb89fgCAgsLDv8IAwAA4gcG/voA/AT/+wYD+AkBAvkI/vr79vz0/wYCAgICDgIE8Qz/APr39A78/vb+7/76BgAJ/v4BEwIE+v4ABhH6+wH38gb7/vb7DfUL/wAMChMIAQEC/v71AAAJBv71/AEEBfn/+vz+9/8DBAL/AvkCCwb8AAQFAPkM+/wD6vAI9wf5+QP5"],
    ["newborn-care","health","+P/7+v0CAREH+/4GBQEG/QEZ6/z++//6Cu78De0O9woHCgMD9Pj/CPr/BAUK+vb89/8A7vL/+vUH/wH6/f/49wkIDfv/8gD0BP38AfUDBOv79P3//vcS9//+6wz4APL9AQf4/Qr+9f/s+gQFBfsCCfgH/vj3DvADBAP18gf7A/T3B/7/9QUH+wX4AfgBAgcBBfUFB/b8A/v7CQUB/QX+/v0HEwUHBwT6BfYJAQ4JCQAS9/4HBA3/EQEEAAUGBvwI9Q4F/v//BQf7+hAABfr//wIC+AABAf0DAQbzCAUR+/8H+gcGDvwC+///9vwEAwYAB/wABQQAAvgECwwE+/j0+QX//v7v/vcPAfH7/AIF//n+Eff3+wT8/PTo+gz0Bfr+CQYK+v8EABby8wHwFPP6CPj8CfYDBAT39/MH7vwG9/kE9gPyAPz8+gQA9gUIAPz6CgD7AwL3BPsA9PsF8gL0AAX19PwP+wkD/O4CEgH6/Pj8Aff3ABLwAwME/fr6APz/+g339PwCAgAF/QH+B//5+/73BfUDAwMC+AMEDPQLDfH8CvgEBwD8+AHsAAIUBgQMCAUF/v4H9gUHC/r9BQP2/f38BwT5/wsH+f0LAgIBCA4JAv8C/wP+BgH5/wr4BwAD8PYDBAUKBgb8+QcD+fn7Aw0HAgb2AAH2+gkIBQP7Bv7sAQgH+f3/Avz18gT9BwX4/gTy/gYBBwb/8gEK7v0E/QQRABH5BvL+/vUBAPkC7/7uAv379AH/9fwBDvzyAfkQDwYJ8Q/1BfEGAAf+AfwDAvz9/P36CQz1Bfr4//IH+Ab6BPsAAvP8+vH3AQIU+wgL/wUA+P8Q8ff/Der8BfgG/fMB/vwDD/z8Aw0D+Qn6B/77Av0F8AAIAfYG/PIJA/32Bv8C/QMP//YDA/0GAf0C+AoB+AgABAQNBfoGB/4D/gICDAX7/gQGBhD7Cwj8BAj8/QL/Cfb9/P8HDvoFBf8B/AT9CBAGAQIF+/nq/AAN+Pz+Bfv6CAcG7wMBAwb0AAf7"],
    ["fire-smoke","safety","6vX/Ce778/4FB/j3AQ4B+QEUAxIe+vkI7gL7+gYBBfcG8AAJAwQGEAoQBxDyB/cE+vr8EgMTAfgBDg0C/fr3AQAA7/0OAv39BAr+CQMO+fv2AggCAAr8CAEADQIADAH2Bv7/+f0CBvEFDAYMEQH//ff6/wX9AgTyAgL6AwL5+fn3AAH4BAMB//f6Awb3/wIGDAoBDAv9AwD9+vv69Qv7/wn+AgIF+gYC8gL0+fAF/PgO+QH2Aw0KBgIB+gf1+Qn+//MC9PL5AgQEAv8E/v8GAgoE/gr6/v/+/wEBAAD3A/cL+/gK/An+BQcH//77AgL7/AQB/AP4/Av0+/3+9wwCBfL1Bgn+8vD5AQT58fgTAfn5CP4QHwP8//EO/PID+QMB/uwADvwHEw8JDgLw6Bf19wQABhT8CwT4B/sO/AYK9wPzBe4DEgD5+AEC/gEAFfT+CPv++AD/+fvzAQAAAwAL+wX/+fUABf72AgUP/PoABAQHAwX4BQsE/v0D+AUF9gT+AQcC//v9/gH8CAIO+QryCPoHBAb6/QD89AL5//UA//oA/AQKBAT/A/wB9AD6C/0BAQD9+wANAgEEB/kJ/fUEAPr/AgLz/gIAAwD+CwEEB/8EA/sNAP78+/cB/QXy/P/6BATyBf0HBgIFBfwK/AQB+P4BBvoE+f8G/AP3+vcN+gvs/hcIDPsE/ADy7/T7BwH/+wcEAx8LCgLyCPD4+Qf29gL09xIFAvkNCgwL8PUA7wnq+PgO9wr/+/j+9w75BvoB+Qb8BADuAvoGAQME+AnzAgYEDgICD/0EDgMWAgEABQT+Bfj6AvsE6vQGCQsGBRIAAQQCBwAC+P31CfL+B/0F9/wHAQX7Au79/wD6A/j+/QYDA/8EAAj9/v4IBwEDBfwBBwn9AAMAAPX6+vb2+RD8/AEC9AH+CAAFA/0E9ff//Qb7Bv799wQJCQYDAvz8+wIJCAMBA/sF/PsCBwUAAwX9AAjxAvsBCv0EBv75B/8GB/38CwL0AAED/wwC+QUGAP4I"],
    ["nuclear-emergency","safety","+RIKFAvz//EGAvL4B/sDBQ4A8PYREhr9//P+6f36BgMHGAkaBQL0BQT9CwP8/+sKBP0ADQMA+wn98wAH5/XyDwkCDfX6+v4BCgX6BvT1+wr6+/wC+/8CAAn4Cgnx+wn69QkD/QL8Af/8/Pb+CfwJ/wAG/QQB/vz8BgEBAP3xBv/99v//BQAE+PgF+Pf9Av///wH//fj8+vP2Awn0//rw+/kG/Af7CQb6AQL2AP4F9hMJ8vYDAfgCAff+//wGAPwE/wT9+/b6APoF+AP//AL6CAkFAAv8+wT8A/kFA/oJ9/n2BQH5B/z4+Pn/BwAB8/v8/wEG//z7B/oG/wD7AQUBAPMHCwz47P79D/jz8xX8CAr/8wMACQgI9P8FAOj5BfkND/sXAAIGEwIOAAMG+/vuBvz0/gj5BwrpAv0IDuvx/A8MCf8KDQX2AQ8QCwMB8gIIAvz/+fcE/+8CAwL5+f/79A36//8G7vT+//kDAQ4T+f8AAAoJBwL4/Ab7B/gI/PgD+woD9vwKAv7w+ff7+AED/wf/BAkB/QAD/P8R+gX89fgABAj9+f//AAgD/QD2+gADAPX6Bfv+/wQB+f7//QMFCgP2Bv/5Avj8AAH79////gP+AgUB+PwAAgIBDgH59wT2Av74+gv+Bv7/APkF9gX7BQcG/P4D/PoC/gz8Af8E/QHzBwUXAPQC5A3s9AkOBQX3+PYJ9A0AAQgI+Az5+QQJ/QAC/AkJ/Pr5Cf//9fgF/Pb0/AUc9/4CBwP5Agb8EPcO+QIH9wP7+/8DA/sM9+//+PsK/vsFAf4D+/4FEP8KAfz5//kJ/Or9BfcFAgILEAQPCQT/+/8N+AQJ+vr9AvX6Af7/Avv//Pv/BAQI/Pz4AfL+//f6EPgN/QP9CPv/Avz4/Pn2/gD2Agr6Af79Afn/BwX+/gEJ9wUC+v7++AMP9P/7DQIDBPv9AQT48wAAB/n8+PwICgr19Ab3CgYIBvwG//UABwf6APMHCff4Avv7+Qn7AgXyAf7z+QX6AQwPBQgF"],
    ["shooter-safety","safety","AgIbBPYE//YB9+4G+AwI9wAOCg4I7wgE9fT7BALtBv78A/wQAAX4+gcLD/gGDPD38wAABfgJ/wf29foL8Pv7EP8F9ff8/frw+g75CPv+Bf8ECQP49PcHDv72BAjxAPsQ+Q7tBf7yBPTu/AD//foBBwIHBfb4AvkM/Qj7+gP5Afr6AAL8AQf7+v79Av/7AAH5BAkHAwcI/fz0APv/AQb+9v4ECPb9/QT8BQL1+fsBBQ0J/P0F//n8DAP5+/kCAfn7+gQDBQf2CfAC7fsCAwYI/wwH8wUC7vP9BAT///sE/wAF9QAGCez+Av8FBPUAAPX3+g0F+AX9/gIIBQX4CAL+BPgADwUB+Qf9DvYC/vkK9939BwkP/PcHA//0C/YN8gMI+Pj3BQL5/f8GAAMABw3z9fcHEwQGA/8CAQMD+/X4Cgn5AgQIA/rtC/z9AAj6AgT4CQb36u8B/Qr9/A37+AkDCQEM+vn8/v7+9QT5//v9+f35EQ//FwcFAPkH+gAD9vv0/QP+BAP+CwP89fsCCAn9+wcFAQMHAQj//f/+AQb5AAEIAAYA//r7/vb0AQH6Be0KBQb6/gf6+/3r9gsF9/wCBfjvAgD89QDuCfP/BAL7BgMEBQECFu77BAUC/wb7AQAA/vf6/wX0+AcA+wIA//b38gMHA/r///sDAf0B+w0GAgT0ERMS+uwI/wX8AP/4EALiAP8TBwH2Ff0F//78/vgC/gLvCAb3Cwb/E/0M+gIA8ffpBAj+9wMEAvv6AAv8+QEF/BP/CQTu/vv7+Pn97/z/BQwC+vn4BAQE/QMR+fkCAgL/AfgBAv788vv8+wD1BQQX9xAJBPwK+AMDCfr6/wf99QAH9vgD/g3//vkC/gsIBPwABPX3Bg8FAQT9CAUS/vv9BPwEBAAI/QgH//8E/ff+CwoE9wUK+v8JAfEJAwL1CwYF8w//BfUI7goE/fr9AP0DBQL2BfsEBQL/9wQB/wMFAgj0/AMG/vn0BgL8/gYBAP8A/gD9BAb6AwMBDAP2AwID"],
    ["cyber-safety","safety","8SYLCfv3CO4K8ff68woH/gcC8wgMDQvyAgL1Awv9/voHCQIABP8G6QcBBwb8AQsN9gMABgoA9v/36fn/FAz9+v74A/v+8f8A+Anq//r87wv5//kN/P0DAQL6+//1FP4C9voA+vjy/AL/AfsBAQYDBw39Bfv6/fwPCQf8A/v8BQcB+wYC/QwO/voB9QH1Agb4Avv7/gAEAgIC/AnzAfkL/gIHAwAGAQn8BAHzAA76AgsH/fsA/QD+/wEDAfP8DPz6/A74Cf3+AP798/r7Af0F/gv++v0E9PwKBAUBAQAG+gUB/QECBAD6CP4ACf4E+vjzAwMM9fP5AgEMAwAKAwP1De4XCg0J9hL9APX1APH//vwE/AYHCQsI9gL5AAYCA/jzAwYL/hD7A/sKBAsH8QAABvALCPkP/gQHAgH8Bg0Q+APyBA8B9gf39wL67f37Av0IAfz9BfcGCP74BhP7/wgMB/0H+AcB9QAA8wDyAvoF+QIDAfsB7/n6Df4D/Pv8Bw34BAUC/QMQEwAF8wT2/AoJ+gH4/QsAAQL9AfQF/AX1CwQCD/j7A/QO/wL86P4C9fsF/fn+Bwr99gsIDv35+wD8Cv//Awr9DPMG+fgAAgkI/f4EBAgBBP33/gMI+fz7CPf99/gDBgQO9QECAgAC//3++v0RDf4A/QT6Bwn9/wP//f/+ExUH9fII/grz/vr8+fr+CgfzBgkNBgQHAPn3AAb78AwMBAYP/APhBPwEBe/3/hEA/AwNEfr7/Pj98wER+PQC9/kT//vwAPr3CPUH+ALuBwP3Bwb/DAP5/fcICPQL9Qb9/fnw7/n1/PsB9gr7DAgABgADEv0ACAkADPcHAAb8AgP/AgABCwsG+QT9/P8NB/sD9f3++wYA/f76//j9/v3w+BAA/wj9+vf8A/kE8wL9BBAE9AABAwECCAAF9v4Q/fr0AfkV+wMAAf74APwB/QYG/vsABQH++gwE/vv//v77/QUB//v6Afr8Bf0H+/oC/Pv/BAP19vz//gIHAQX/BfwF"],
    ["pandemic","safety","AAAC9+/w8vcI//f+/AH8+f//7wMIBwX5BQIE/AUBAgX/B/8EAQD78/wFAPoA9wv58gkE+QYS9v398v8H/RTxAAX7BPUP+P8F9AAFDgL98fX8CQAG+PD/CRTy/QH0/wACAQwD8wL9+/QOBQT6/v3yAf4MAOb/APwPAQn3Bf/xDQD1AvIIBgcCAPv//fwAB/L9/AMAAwcGDPP8+QIRBwECAAj59Pb5//73AwII/wkK+AML9v4D/QIH/QL6B/kFBP4P/g72BQD9BPoJBP7/CQQCAfwKAQkA9PQFAwX9BQYM9gEAA/wAAuwRCv/8AQL4+/7//woJ8v/4CgUFBwUFFwX6CQQKFP748wL6Avbt9PUEAP78/QX7AQoTAQX99/sE+/gFDQX/Bf387vT9Cwj2AQH8+OcP9QEJBP/05v73/wAE+AMJBQDtBO/09vcI8f0RCf0C//38BfsJBAUP9wT2+gL9/QIHCQMG7f4A+AIEAgcB/QUHB/j7/QT+Dfv8/gH3+An9//77BgcC+gD/BPX6+v/8/Q4I/gUFAPsD+/QA+wQEBgIS9PEC+AH/7w0A9gcL+wMLBvH4+/7xCgYBBwX19wECBvwG8AD/9gMA/fgAAAkHAQgDCQEHCPcDAAkO+v35D/cE/wID8AT3+gID////+fgD+AT7CPny/wT7CvoF/gUH/Q4HDgsD9/cCAAb39PTyBP39+v0H9QMBCgH++wcDCPv7/PrxCAD2BfT5CPr/A/YH+AD+CAT2//n1Af4IBw/8AekI9PwBBwf0BAztCgQA9Pj/+QUO8/rxAAXvBf0D+PkJ+xT9BwYF9PMI+QkA8/38BPUQ+wAH+AUQ6gL4+fwB+gQC/Qr59QEG+xH/9Pn7CgoA+/4ABgf/Cvn//gL3B/cHEAMCBgED/gQCA/UBEAEDBQX1Cg0I+gAB7wD49/cNCAEBDwf5+AUDAfb4BAECAQsGAgUH/fv8//nxBgYFC/0EAPb88QL9+vkLAQMDA/36/wAF+AAHAQUFDAQGBe7tC//7Bv/+"],
    ["extreme-heat","safety","8P4BD/kD+foK7/IC8QgLBPQOBhD2AhcA6Qr87/f8CP79AQQN/gHz+Pr9EgvtAQHyBPj/DPP4/PrwBgISBwb38Qb+Bf379vsD/AT7Efz9+wAG+QkADgsDBPkFCvb+CwIC+fzzC/gI+w3z+gn1D/cEAwMHBQn5Av/9CAT8AvwBAvcK+/cAAAAADPgL+v0IBAbx+g7//QQEEQH//vf3AQP69AEJ/wH9BgQABvn7/fr2AgT+BPn69wwABfz0C/UJ+gsDBgH69wAH+QAHAgYKAgME/gf7BQL+Av8PDAT7CgL1+PUJ9/cH+PgB+/8B+/75Cf36AfgH/P8G/wL9+/n3APf9BQn4+Av+/gD//PfpBPwNAfP7Bfb1/fQB+/QE//T/9AsJB/oP+Q8LBP/4CAz2+wXwBQz4+gkUABAF9f74DgABAv7/7PP4+PMA9/UCBBAR8v8MAAb9BPz6BgnxBAEDDwIM+/MC+f0FCgQC9fUH9gUNAQH8/v/7DP4C9AL5BwD8CA8BBAD7BfgCDfzxDvbzCP/8+/X9/PsDC/cK9voIAv8G//0GAfj1/vr0AwD3AfL8/vsH+gL8+PsBAwD8BAD5BPf2+Qz5BPwD/Qb8+vgNCwQHA+8FAwEIAAsDAQMD//kGBfXx//37AvX0Bg32+wf8/Pv5/v4BC/oK+AL7+QQCCAf8BQn2+AoI9P38/Pvu7gTzEv71+Pv/Av7/CQX0Av32//MCBQoC/f8BA/sA/v0WEu4A7/v7+QEZA+sE+uv/AgIEAfL//f0D+Qfp8gb3A/QPB/YACQ36AwoGBQv5AQIHBwIG/gb3+u8L/AP2DO78+/UGCQwCAwf7/AMKA/wB+fMADQEBBQ38+gH4/QYM+gb9/gYI/Pj9AggBCwIGDPv49/gBAfDs/QP2+/gC/wED/fkB/v79DAD69/r0DAwF+/sL9AIABQUAAf0BAgQB+wn+BgL/AwcACfYGDgMC+hAL+P4EAP78+wn5/wL49v4H//8C//IF//v7AQL49gH3APj++AMC/AQB"],
    ["cold-injury","health","/vYJDfMF8vT6+vcE8wAA7/UEBfAABwUOAvUS9A36AwUDAAr//gQH/f39AP76Ae/8+/L//gj3BwAPB/gH8wQN/fYICQ0N8gfy/Pb7Cfz5DBH2AgIC+QIK/AEFAf0OAAH5/wQCBgX8DPjw+gj9EvwABgD8BgII+goBBwAFDv0D+vP9+gr6+hYSAwcN/QH/CPIE8fQBAQkQ+gUCAg4BD/z2BxD1BAr3BAT/+vv8AQUFAfgE/gQA/vwG/QoABwQDAf8RBQAC9AL9B/wI/foICQP4+AQEDgcS/wL4Av/+De/7BfzwBAT2APsFAfgDAQADBv37/w/7+/4CBwID/f8BCf0MAPD19f/y7wfw+P72BvcOAOj2DvwB9wAEAvr58gn3+QP3CAUZ+QP6CPz5B/34+QIBDPXhB/r8AAoJCgsJBvX/B/7v+AX7//z09e72//oE6/n7/AL0+fX/8/r3/wL3EPv17AAK//8P//n/8gAWBgD+/v39+P3+DPoJ7wP3AAX6Bf4BBAgB+PsIB/X3DgIECwUA/voFAgX9AgYA/f3/AwwG8f8JAQb/BgQA+wgA9v0OAP/7/vzt/gQB/woBAgT+Cgb4Cvn8AvwEAAgDBAH+B/3//P4DAA79CAUJBgn4///5Bf0F/Ar7+wD++vsA+vj9+v0H/v3/AfcC+AYA/vcD/wf6BQL7AQIR+/oA9/378ffyC/v0AQYC/wILAwX15v37AgABBQUAEAQKAf/7/QT7APAO+xUG9PsA/vcKBvsF+/sFAv///v38CA3y+AL3//YF/+oME/kIB/3w9v3+/v8G+hP4AAAL+fgDBvgIAf0BCf8H/vb8AAD9/wv/B/j4//oIB/T5/PsFBfYCDQP/7xD+9wwE+PkCBAH09w0PA/v1Afr/AAX8DQ8F+AH2BPP3/PgBCez/Af398AQFDfX8/v4MCQIG/P3/8gAEAf4BA/by/wX5BgQBCv8EAAb+AfkJ//f7/wj6AQP0/P7w9vv/+QX+BPUGAQEBAgv1BgIL9fbx/gX/9/gQ"],
    ["disaster-reaction","safety","6Q4NCA33+/UF7OL5BQL8Bv/5/QP/B/346/EKEwEFAf4FAQ36DAAK9QoKCQD4DP0J/Q/yEP0M/vgBBAEA8QMFDQz59gAL+fkP/Qz5AP/1DBL2Bf76AP79/gQDBPz69fYD+/ny+/j3APgDBgUKCwnzAQsG8wr6CP/79vz6CwT+/w4J9vzz+QQEB/0G+v8B/v4EAfr9//4D+QH++/r1B/gB9fEH9P4H8AcABPj+BPf1AQ8F/QEMAQgD+Pn9BwH4AwT4/fsK+/z6B/n2+PwB9wUHAQr1+f/z/wL7//T///oJ+v8M+AIG/fr4+v8GBAH8/QID/voBAgMHAwL+9f0BAP/1DOoFGwcH5Pr1/OTsA/oN9gUB/wL5/gwDDP77AP3tBf7//wYOBvn2+Pr8BQb2+wH4AOkI+gAE/vf96gX7AvkHAQ4A/An3Duzy8P0D9wL8/f0B//cC+voK+f0C/gv69gL+Cv4J/wH58/cB8/gHCPoCAPsWBvz5A/38+/cBB/X/BAoABgD6AgUCAf8BBPoEAwH1/gMNABABBQABAfn3/AIA//4HCf0QAvkH+wUB9gIC9AsJ/vv2/wj3/wH6DAr2+gcEBP0J+wAC/gX8/PL2BgkGAwYMAQITAv79AgQNAAH9Bv8D+/oG/AP4+gAF/wP6/fP6//37Bffz/fb//wAB+ggACwTgAhMQCOv8+gDw7PgL//0H/AcABQkI+gT3CPz+8A4CAAESGAr++gHz9vj8AvwBAwXqCvX5B/wBAAb8/QADBwD+CvsQ+QH69vr4Cv0JAPwEBwH8/Ov8AgL+AvEI9QT+BgX9CwT77/kCAwcEDAP////4AgIM/Qnv+/r6BOoJ/wMAAP/8/Az6AwH5AQwB9QcBB/30BPn9/f0K9wYA/PAO/AD+/BIEBwQFBfsN/vj4B/QB9QQMAQQJBv39BQYKDgX6AAb/AwMABQD6+wkDBAEBCwn7Dvn/Av0E+gL9/v8HA/kAA/MB+hL8+vz9Cv0ABAQFAAUEBPz3+fgO/Qf+/AkJAQP/"],
    ["outdoor-rescue","safety","8wkMEgACCPAH+fry/QDz+gb7AwIDCPsB+PkK/gcD8QQHEwIA/+4M/PgAA/r8Bvz77v3+/w37/Qf9/vv7+v7tCgn69fcH/f8LAv4BBPsGBQ/7+/8J5Ab7+/77//f4B/4EAgID+wL1BvDw+wQE/QUBBBAJ//z9+fkJ9/0EBA7/A/b6BwAFDwgO+wID+Qn7B/v3DPn+CfYD/wX8+wHpBwD6+wj/Agv3+Ar08/j9A/j7Ag0ABPT7Af7wAP4DDPX9A/7/+v76AQX4+/UH9+/uBv/0/vwG+hAO+fv6BgQF+QIM8Qb9+/sAAfb/AwD6/gAE9fgACBEJ9v4E/woG/wgAEAUAC/kKFgj/Afj19fP49AsB7AULAgICBgL3A/v4AP76AP8JBgMEAfX3CQD9+PoC/BPw/fcEBfkS+P8F/AMF//35AhAJ8fP2E/n9BAP+BAT4+f8F+wMF8/IH/Pj/+gv9/RADA/UR/f7//fMC9gMDBQID/wYIBP71CPXzAfMABAIP9P74CgICAgf/DfX7A/4HAgfz/A0IBAgE/P/89gT77PgIAP3wCf4R+wAE/QEK8gf+7PwMBvv6AAsB9f4DAhAC9Af//fr1/f8A/P78APj59AIEBwML+f4H//P7+AX//gEBCfcG/gb+DAb89wsA/wUFAfYFBgUK/PH6APIE6vb/Ag0J/wb0BhQTD/MH+w/q+/oM8/QC/gf7AgsJ+/Dy+/X8//n9CwkHBwgC8vT7APT7BOr5Af3zAgT/DADxAP4DBf/s9vkbBwb8/v729A0BAgAJ//n5+ggEBvju8vcGAv36+/z6AgL9/fX4DPYO+gcACOwGAfkDDgD+Av338gv5+f0DBAEP/gQCAAMDBPsK8gIAA/cE9wL9Awb9//349PoCBPgCAv8C9gT6A/f/BwD6BgH+BPn8EwL3/gL3AP37/gwDBPn6C/n3Af72BfwCBvv0BAcF/APyBfMCCv/5CQH7B/j9+P37+/r0/P4D//37BQYGBP0C9/oFBgj8/f4C8fQC/vYMA/0I"],
    ["stroke-signs","health","3vT7Cfrv9/v2A/T6BAAN+P/+CAnr/PQBCfoHCfkICwsP9AYK+wf+/e/6/Qr7Cgv/Egf4/wf+DgUCBAsA9P4GEAUKCRH6AwAD/gUD+wj96/j+8fsABv/u/AT8BvcJCwX1EAf1+AD67v78+wIFAu4T9/4IB/j+Dv79/PcP+f4EAQ0CB/z//gYEAvX09f0FCP4J/AH6DQoM+vkMAPgJCAIFB/wF+wkDBwIHAAz4CP8E/gP6Bgf5BwIH+/cDDgP7+wX4Agf8+Qn8A/8G//4G9gECAgMDCgYABvv4/QH7AwH9/gH5BQEB/QMBD/0C//v7//0GBQP+9fcJAwX1+f/6BgkD/ewF+w0GAw79AfoJCgYF9/j6CAoD/AT+C/30AA3q+QT5+QwAD/b0DQT2AP0WAQEWEQn59gn0+wAR/Pn6BP4DAgT+9vz79QoB8/8EA/ME7Qb97gn5C/QA8f74+wfy+AP3BgkKAP0ACQ0ECAwEAv/4AQIB/vX99Q0B/AAGCP/9//AF/Ab7/fkK//77/QMADA/+DP4JDPYI/Q74+wMIBf8EBAAM//wFEAv8/v4D+gMDA/z6/PsEBRbz/Qj29f0CAv0EAQb2/PkSBgQDAPX4CfUB/QIDDQMNAgX6/PkBBPb2B/oD/v7+/gT8+QUB+v8DAAD29fwMBA0FAfz7AgcG+wb//wTs9O0C+/gNCOr79fz47BntDPgS/vTy//0DAA//BgP6Cf8IAf8A9wP3/AkFCvv7BQv/9/Xy+f38AgAO/gEACA8SCf8JBfwS8vv5AQUACPb9A/AA+fr4+vbzA/v/6wH4DvsHAgf4+v7zAfIJ+QD6BAsC/wALBgMMBvj/AQX+/wsC/wD//v0H+w8F+AkK//MB+gb7/+sKCf39+gf/APwF/g0C+v7+DAL0BAUCA/0D/wH97wL8AvkB//8C6vz6APb6BwQEAv72AgAC+gcK9gn9/QQF/AEBAwv+B/UB/wAL+v0D/f0BAPz8APAOBPUEAP3zCf3+9f0CAv0IA/z7BwX+Bv0H"],
    ["electrical-fire","safety","+PwHEu/9CP8C//II9wcA/QoNCwcJ9v/39RH98wwG8f4H9vH//fPtFRIGAg797/wO/esCFfr+BwcECQIIAfn0+PEU+gT7+QEL/QgCBAIF/v7y9QAAAvn3AAf3C/wHBwj78+/6AQsBDAMDCPsJCPn9CPsDEQP6EAwADfX8BPj3BPgEAwH8Cfr7/gQPCvn3CgL8AP4AAgMKAPz99/r3/AP6AfX+AwIE+AL5A/YC//4P/AD5+wAG//8NBvcI/P3/A/j+Bv/2/AADAf0BBwEF/vX6/xEJAv4E+v3+AQwJ+vr8/gD7Bfb//wrzBAkA/wQNAvr1/gMB/QgOCP0D+f8G//kEA/T5BAv38PzvA/f29fgP/AYPDf4NGgcI9PML+PQGCQUCBu/1AgEH/g0H/gIT9g4C+wLzDhH6CQf7BgcD9BEJ+fz6AAUFFPkE/wYB/QIMFgIDBOUJ/wb/CgUFBPsIBggNBfz5/fYEEP0M/QYPAggGDAQJBwEBBwoBBPoAAgAI+wcKCAj7AAn7BwL4/wUE/gQFAgb9AAMEBQL1AQH1Av/79AAF+v0ECvwJBvkC/v37CPwGBgH89/0LBf4GBvoCA/cJCfj5BPv6+Qj9CQgDDgP//QEHB/QM/P79/fsH+QgB/QL6Agz2Cf0C/gwFBfkI+f0G/gX5BPEA/QcBAQX8+QEK9Az4AAwe+vYG+fcD+gL7BwvwBQ/8+xv7DA/yAvX7+gH29fr3/PsFCvQbBf0GG+//Bfr6AgMTAAv6Af4V9wUA+Pj+AwL9+fv19PT9DPYJAwoDAPgAAw8L/PPuFggM9QYF//b+8wP5AA/5+P4JC/0F9AUHCP0HA/YA+/8CBfr8A/kL9QQFAfsC9wL7/wEB//4G+gYEAf//+/8F+AUK/v/yBAYICQUBBgX/AQIC+gT5/QT6AQT5//oBDP8E9wD7/wEJBAT+BP3+9wEJ/QL7//wH/fsICgv+BAEF/AgKDgb/AAIB+QkD+gUBC/4I/gABAwMM/f75AwP8/P8BBwjw+f0BB/r9"],
    ["carbon-monoxide","safety","9gcGEv73DQH6/vUA+CIMCPn/CfkGAgEW+hP0+fcX+QL3+Qr8/gQOFAMMCP7++uz86/0A/f4DFgAA/PwL8P0GCf8N+wIM//sKA/gECwAA/vYGAPrz8f/5AAcE/PwMAQD+/v/98v8EBfT8CAj9/fsA/QgGFAv/+fz69P4BA/z5APoA/gECCgQA/wP6Ae3+/gIIDwf/DvH//v0EBPz5CQD3BwEBAvn9AAUFBAP6Af76+PIEA/4DAAX9BPH/CgP6A/0J/fcP/P0CA/oIBAAL/wYGCf3vCRQDBvv9AwH/BwH9Bv/9/wMP9fUBBAP79wMD//n7C/8D+gAD9vz/+fcA+QYFCPwBDRkB/wPxB/70/QEZ+Ab/Bvr19Qj09vT++/gA/Pf4CP77DP8D+hH0AggKCfjzCQn89v768gvs+Pvv+AUI/P0LAxz1+Ab//f3nBgsN9AD0+QX5Avf8B//3Afv79wgKDP74+/AFAfz9A/gKAf7+DP77CggA+f8NAP/8AgIIDfsA+AL+AQcB/vwJAAb0Awz/+AYA/gH9/wHu/gr9/ff4//0BBBEH+Pv/CQb/AQkE/f///vv7+QAOAfP79fz7+P77+QT/AgX++QL+BQD+AQkCCQED+gYC/Pj59wcTBfn/BgIA/vL3+w367woD/AMEAQ/2BfkIB/oCAPUADP7/Cfv/+QTs9gIQ9O/5Bfnx8/b4Cgv79wL7B/UG+fXt8AAB9xACBxf4BgT9DAUK8wwAExAB+fj3B/oKAQz89fUK9wn/Ew74CvT3CRIA/PUEAwEDCQb3APwFBv8CCPoD/vkD7Qz6Avr7BPQABv8L8fr5AwX0BfgIB/oCC/n1BfID9Aj6AvQD/wf/+PoPCP0E+/77+f/7Af0LBPMFAQIC+frxAP8H/PcEBQQF+gD8/wMB8vn+9gH3AAYJ+gD8Bgj+9wT9Bf/++vwK9P0A+//8/vkJAQcH/gAN/vf/EgD+AwcHBfb/CQD49AcK+//9+QD6CgYBAAIHAPb0/gH+BgsB/fz4A/8BAwD+"],
    ["gas-leak","safety","7O35BfH5/gb6+ADs9RoBE/0P8/sOBAsF9AX28gQNCAkCBfMH/QcGBff/Bw7sBvP5CAII/vT98//yBQT2A/f+8vcE9gQCARICAwgC+QUI9vry9gUFAwILAvr7B/UCBgb/Ev788fsKC/T89BAHBQcBDAH5AAcEBwAABAb7BQf9BAL1DfP/AQMD//UACvkMDgn/AgYKBgMAAvoD/QADAwL4/gH8Ef8DCQD4+Ab9+/YLA/kJ9PoCBQUC/QQB9AT8+v4G/gMBAOsAAf75Af/6AgMAA/8J8g4D/BAC/P4CAfkABvwB/voGAvz4/w38+wkE8QcCBgn+AgUE9gME9wID/QIBCvQD/QIA8QT1+/j3/vwSFQYH/vkLGvQH7vf6//35+APy+AICDPwL9QgMC/QA8QIFFQ7xCAn6AAT8+Av9BwQA/Qr9EOz7DvrqCP4L+REKAvb9BPj+EP0DAAoBCg0TAu4CAwP7+Qn2+f777vkG/gP9CQv2AP3+AAoG//8B9An//P/79v/9AQEC/f0B/AYD9PsDAAADBgb8Aw34APz8/PQKAP7+/v0AAfr9+QIJ+PcLAwP2+wL9/P399AMG/v0K/gIF/vr/BPj9AAf99gIICQH2B/D+/gEI+PkCAv32BwUD/P/3AvT5APIFBg0ECwb++/sH+APz/wgC//z/9vwB9/gE9QP1APsJ6vb1Bvb68/P3FQgIDA77Dxr29wj29QL+Af0G9/r79REJBgoIDRACAvsLCgoM8/oGBAD6+wEMCfwB/fcABgT58goAAvwHBvz//Qfw+vT9EQr6FggG//4K9fr9CfkCAvz+ARH+8Pv/BREBBvgI8v4GC/4DCfkCBPcJ+wT7/P4E9QX7+wH9+QH9CgUD/v79CAAH+f/+8v0B+ffx/v79Awb/BP8B9/T0Bfn9/wAA9Ab6BAEMCf4I+wD+Bfj4BAUE/QXu8/gBAfwKCf8B/v3//wUBE/sHCQEF//34Bfb39gQN9gb8Av4JAwEBBQL5B/8ABvX2BAX6/PkE/wTyCgAA"],
    ["house-fire","safety","9/sJD/8C/fP5AQH6/wD59/oMCBAW+AsL7Q70//398+r/7gAM/Pz+BwgMA/P5Bur27wIEDQII8gX6CQIU/Q0ABQb+8wsL+fn3+hMCCv8M9AkDCA74Ag7y/f4MBgMJAf78+wfw+Qj6/u4FBAcCA/oF/fX7+v4CBwcABwHz/AICB+/6AwD/APwCAvoHCQ/zBO8BCAQHCA4BAfr8/vb58xUFCQf6CgQA+f75/Pv4+v0G/AEJAf37BggGAfX/Af/4/QIB/v7++/v5CQAD9AEACQIEAAsIAAgD/AMB+v0GA/cB/fgF/f0BBgL7BgAN+QUCAgH4/wABAQb9AQ36+vr6BwQCCev3CgH+Bvn39v/88vUM/PbyFAQUEAgCDPYIAv4A+fr7//b2FQQHARoPDgL0AAH59wD5+gICFf0H+AUAFvYG9AkDAP75BAAC6v0JCQn7BvcK/wMF7v0N9f79BQoA/QP7/An7/fb9+ALm8/4LAP/5//v/BQIA/gUAAPoL9gL///vv+vsA+wACAf79+gMP+gDuBAEJBg0ABQYB9v36+vYA/vQG/QUL+fv4/vwA+/rzCPgBBP4A+AAJAATy+/wB+wYC9wH1/wDw/wMAB/YI+wv7BgT8BgEKBPn39wQBBPv2AQL0CPn5Bv4H+wr5BvkF/AT+/PcBB/QJ+/sG/vkA/QIGAQbs+Qr7+vj0+Av89e0AD/oCBhL1Cxj7AALoDPv7BAQPAP/7/g0CAwoH/gcJ++4Q+fkH/ggJ/Q/++AIEDQAFBvP8/vv79AUIBQADAv4ACRz1+gH6Bf7+BQQFAv0F//8H/QYABPby+wMJ/vwHFAgOAQgRBgX5AwEE//n8AfwKDfME9/gD+/0KAv//8gIC//8JCPwDAv0H+/38//z7//n+BPj4CfwAAwb/BAT6A/X+8/0E/gb1+fz7C/8DBv35/QP7Bv33/v3/7fv7AQL9BQsG/f33CgH0DP7x+/X+DPcK+wL19AgE8gX/+/8EBAICB/X/BfgGBgrtA/0DBPoG+ff5FPsJ"],
    ["flood","safety","7AUQGAUB/O7+9vL18AL4//P7Av75AAADCwQBDwz4DAj+BPnq9/IMBfgJ9vXzFO8BAvUD+gD+AgMC+vr9+wEDAA0FDP8D9BH39fL89gL++wzz9AUA+AUDAgb+9foA/fUB9/31AvoK/fQCAgH49P/0F/kB/gIG+vP79wYBCATz+vn7/QL6//wFAQQLA/0AAe79AwIE//4FAAgA/f3/CvcAAg0CBw71BQkF/fr6+v/8//QFBQH7Bfvu9QP5AQX7Av4M/fj7+AL4BAD6BQX6BPn9+BD5CQQAAgP+BfoBBRf3A/sK+vMF+v4BBP/6+wwD+fb4BgkH/QIF+Af/AvwAABECAgEEDw8D+vP2+PLt+QMJAxL7+/L0Duz4/wgAEvH/AvIIAQ7zDg3t8/307//yBAEQ9f8F/QMM/fkN8/4EAf0F/AgF/QMC/vML+/gH+vz59/wEBwAGBBgQA/sL//kC9QXw+ugL9fz5/vcB/v/4APMGAxD3AQ74AAf+/fsC+wj8APcHEfr/AAEECv0JC/wLC/8A9fsB9PQABvn++wr+/wMG/PgG/gIH/wMC/Qb+BP7/A/0A//n/AAH4+wH++AcFAwkDAgYG8vz8+QEFDQP7+wwEBwUUAgH8/gEC/vkDDAH6/wL5/v/8+gD8A/T+/vsBAf0C//YHA/v7/Aj+APf+//YBD/v3Cwse/fcA5Qbu7gH7CQgI+/0B+xDt+PsR/Q4F//H2BAEI8v3/9vv0AvwC+/z///jy+wIQ+vwMDQED+/P/BwMQABIA+gHtDPj3A/v++fv5+wH7Bf8JDQb6BAf+//QI/PrzAff9APfw+vcB/f/4BQMcBwAI7QQJ9Qr3//AE+vf3+gT3+Pn5AgkG/AcH//n6/fwE/vz8BAP/CAwD/v8QBPv1C/wABfn8AAQADP0ABfUDAAMH/Pz//fn4/QEI/QEEBwcE+/77B/v9CAb/AfEEBQHxDvwGAP8A+wb/+gsBBAEB/gj8AgcB+/oBAv79AvL///n7AwD3/wQBAgAJAAHyDAsB"],
    ["earthquake","safety","7QEQCPcA/O/+9vIP/gX79Qb/BAcQ/vMK+wP/8v/+BAPzBvr9/vX//AAAE/z7+v4H7QLv+AME+gQRAAMB/gP1+Qv8DgT2B/f0AQcC//z0Egfz9gPt8wUB+wbyA/cP9/cQAgf/BgLtB/8BBRELAvbw8wYGAfL8AQIMAQfyBAMC+ArsCwP+//kN7wMFBvr5BgQE+fz7AQT+CP/6/wX/CAUCB/3+AAD8AQ4HCgP/BPP9/gYA/v4JAfsH8/z3BgcJ8wYEAA8BAwsAAPkEC/gM/f/9A///7Qv9+gX2/wgCBv/6/P7///wABAT9CPv3A/gJAA0BAPv+Avn/BwIG+wsG+PoJ+vAEAvwACO//+QT7+Qf/9voACPcQCgbtDekG/A7yEgL8DAcGDfwB+xT0DPwIAP39A/YO9v4EFPb7Cv8TC/r6+AQGCwPzCAj68/IOBQP/D/0CAP7/APwAAgL3ARTw+/z0/g8OEv738QMAAwUDEPv88fL8BvkDAvgJ8v4F+AP+9/T78gMHBPz8/vYHAwPz/AEKA/4T/vYFBAH4+fADBAX1+vb+AQICAwD6/fz6AAD19vr6AQH7//YDBv7zAP/9Cf4EAP76/wL+CvgG/gcMAwD4/PoJBQMF9AD8Afz9BPwC/fwAAP/5AwAJBvYEAwT2/gEABAADBAP6BPsFDA4OBQIIBv/6Bv8C/AH49v3t6O4FBP38+gADEgkE7ffx/u8D8AsJDAUEBwv/BQD/AQv5EgD/9f3n//wDBQf9Cf/79gz2+gADEPz/9v379fADCP8J9wAAAO79CvT4CwUIDff/9voMAQnzBwMD9e37/vP6DQ4H+PcBAgL49fv89AEDC/n/Cfb9+Pn+/QkBAgf0+Pj1/O/+Bv4CBgIA/fwE9wD4BvoJ+QH2BQgF/f7/BvoGAQIF+PT8CBD6+wP3A/kRCQP/AQX8Av0DCPz7APUA+/wIBP0D/QUCB/v2EAHy+P8FEvkFAgPzAQQC9wMFA/gEC/r/Afz0AAT5AAb4/v0I/AT/BfkACAH+"],
    ["postpartum","health","AP/69f7u/wwR/fcLA/X9B/4H/ffv/AAI+vUGAQj76PT9AQIDAf3+A/3t7/IG7PsLAf4J7gcCB/z6CP/9CQfu/P77APwPCvoO8QP3/P0FAfYA/PEB//UEAwz++QzyCP8F//f6AwXwBgH0/wkH9u3+/P8C/BgDBQkJCfv99v398vsHBf4B/AT8/QIL9/0BCPIA9/kF+gMD/QcACwcG/f4B+f7/Ag8J//4CB/QJBQAFCQIA/wn//wDzBfwUAPv//v0F+QP///v9BPr/CAQG/wf4Fwr0BAIJ7w72+v8EA/gJ+gYB+QIK//n7+wUB+u8H+gEIE/8AAP8E/vn+Bwb+A/UHAPH09P71+PkEF/XrDAsB8gL8EO0ABPYIDQD9CQL7B/D7BQMCBPr8+wrv7QIJDwL8/vf4APQDBfH6/wQABQ358AoKBQb2AfgBBAEMAwb9ABD5AwH/+wD6DfwCCej/9gH2+gX6+/sF9wQH9PIAFQP+AQP/CwgJBgz1Cvz29gEGCfb1+/8A8/UBBv79Cf31Cgb+B/X4BwQKAv0L+An4CQAJ+wP+9AAHDwP1BAX5/Qb2CAD/AwD///4GBv/y/fsHCAD6Bf73CP77BAYKAvgJ+QUJ9gv//QkBBf8E//z/BgoFBAP5BPv3AP/1/P0D/gL//QkCDAz17QYA/v/7BgkB+vwBA/kFAvUEBO/3+vsA7gEQAP0GDQL0Ae73FAMD8gn/CQb18/r0/goMAPUQ+PgB+/zxBwj7EQnkAwcC8v8BEgIFCPkIDAIP8Q8CAvj/Cv/7AQT6/fUB9wn9+v8C8Pr5/PAH8AAR8vjtAvsG7vf4+AUAAfwGAQYKBf/3B/3/+fgL/vQI+/b4DQkD/PgFCP8JBQIM//b8/fj4+PgFA/gGCwH8Bf0P//sHAQz6/wYF9woL/gb4BwADCfb/CwX9Cg36C/8H+fz7BAUG//8C/v36Bwv/AQwCBgT/BAH3CwD7/fwAAv7/+/8BAPkG+wX//v399v4GBP38A/sHBAj78gD/BAQF/AP5"],
    ["chemical-eye","health","8fr1E/jtA+0M7PL3AQQIBg0eBQUP/QIC/AMA/AcCAgsB9vYABP0E/grkBAP/Bgz69wkQBw8G/f0O/wv7GQUBAfwC+w8ICfwGAAbz/xAL8gEO+AkAEf4E+wEB/wP+DAH/BPsD+vf/9wX9Bvb1+QwDFAYL+AUPB/j59Pn+/AX1APkDBgH4A/IHDwH9AQIL9wEG+gEGC/0F+wgFA/78+v72+gD0Ag8J//sE+gb9BAgCAwn6Av389QUCBf3//PoJ/QEI+vwDAQr7BAAD/f0D+wUC/Aj99PwD9/r8/AL/BfsBAvsCA/4Q+QII/QML+QH5+wMIAAIE+/gBDQH5Cfz8+Qn5B/D+/Rbu9/779O7x+PkBAQENDwcN/QIEBvf7BQYA+wATEBHz+vbrC/sC6wUCD/cJAfz/CgMRB/7+FwQD+Bf8DgkE/fgB/wQBAP0H9wj9APYIBAMSBQUGCv7++//99gT/AQX79wb/AAYF8/37B/kJAA/yCAH+/AP+9vIIAPsCABADAPkB+fv5Bv0IBf3/DwH9A/3//AH/CfAA+v0MEAwE+/oCAgcR/Pb8/PwBAgwKAPwI/Pr8AgAE/gX+//4CE/f8Bf77+/gAA/kE+wPt+gwAAfb7A/z8Cfv1//0H9P38/f0BA/sJBf8M/AH+BvsEDf72AQYJBQT5APkD9AME+wb/BAbpAfgK9gEO+wL27v7/AQsCBgAI9f0J/wD8+/kQCfYIB/kAAfsD+xQF7QoC/QL87wL/BfQB9/D+7hIXEAgC/AgIAwD9APICB+cJ/v78AQH//QD6Cvb5B/z3+Qf4B/YO+PYMAvwB+gj3EQb+/vX9/QoH/f4DCAICBQL5B/f9/Az//PkKAfMAAf0PCAMCAf4C+/8CAf0G+wD7+wkCBfkA+PUM+wEGCgUF+w7//AP6//gH7QD5AwzzAvv0/foL+g0JDAj7/gf8CPwGBPYA9/4I/QPz+QcH/QsH/gcAEPkDBQcD/QgA/w3+AAMJ/QcEAQQB9QUB+/8EEwwI+/wC/wb4Ae4H"],
    ["electric-shock","health","5wcHBfv69gj5/AAF/ffq9gYAAQH8CAkPDP/1/vsB9gTz/BQBBQT8DQH08Av9AwP/+fn9+/f18v0OBgUQ8/T+/AL9/+0G//z09PkCAff8Bvn6+QD29/j2BvL59gH2APz++Qb9DP4DBAH8CP0LB/z6APn7EfwQ+wcB//v6CgD67QgEDwMNAAL+9woEAwgDEQL2/fUN/AHzCPYH/f/39wP8BQ0BBAn+AwMCCuwHBf72AgT19QUD9Q33DgT9DQIK/fsB/gEFAQIDAfYAAwAC+v33BQkS+/31//4A/AT7/AH9DQECDfb/+QL5//749QL5/vMACAn+CADzAwsNAPoLCwMMAfIA+RoE+Pf7//YPBgQA++wH/xT1CBgM7vj0+v8CDPj8+/X+Cvr6+Qn8/gANAvv6D/T3//v2BAAYBhLtBgr5+AnuAA39//0B9QL3CAbz7A8G8PME/wwBAgD09xECAAoHBvkI/wL8Af0JCgMJ/Qf/+gQMCwgDBAkI8A789/T9CP7/AQgC+/8J/fwD9QX6CQoBBQIABvUPAQMECAgF/QIJ/PsB+/r8Bv8EAQMLAwn+/vn5+Q/5/AUBEgX7+PwKAf72BAb7BgUBBf/9CQoDBvn6AQUFBf8F/Qb6BAEK//z/A/0F/AcCCfkD+/32+v4H+vz7/fz//f4N/v0DBAAC+wX/BgTqA/gT/O8EDv74/vUJAgACAQgEAQQOFPH5+v8C8RwA9gb5APwE9v/6+//8B/v89QD0+vwQCgED9/4S+gwU/v71BQL5CP30A/b7+/QG+//9BvP2A/r3/QP4B/gB+wcEAgf//fv2+gAFAPcKAQkH+AX4//4OBQT+A/70B/37//X48gYF+P72CwAG7/gC9QEMAPsN9f77Cv0O9QL4A/kDC/IC/f/8BQD+/gP7Cw0J9QoB9wAE+vv4+fkG+/4PCAgC+gb18/gM/P7r/PkF/Aj49vz5+gcICP8BBQYBCADz/fr0+QAG8wMFAgH/+fkH9QTw/wkC/Qf6DQEEAQgEAf0FAQP4"],
    ["drowning","health","6wQIDgLo9vv25+n9/gPwFP0MEAMFA/cCCvcR/PD67QMDCwT2BPgP/f0H/AD3CAQF+vYFBAD7+P8P/wT6/AHxAwgACRMC9QAHAvz5+QL57wQE/gkGAwb/AwEPBAMJ9gwFAw/28QkKB/b3/QAF+v/9BQMR/QMB+gD++QABAwr09AcF+/v7AgsEBQL/AP8IAwD4BP/8C/3/9gAL/QH3Cw0A+/0LDwsE9QcM+Pv4BfoDAP30Af//BQP7Afb9G/3z9gMC/vv6/wgB//4FC/oF9vgCAA4ICPwF/gn1BQD7+v8JAvj6/P7+BvX9BPgBAAX7+AP+AQ36BPwCBQAE/P0CAgr+APr3Bg4D+/j09/D6//T/AAsACgD9/fMHAwbvBwb9+fT/8w75+PkADf7q9wf5/gIB+xMC8gkB9gUJCPUH//Ty9A0T/vsO9v37//34Bu4C/PwHCQP6+fv8/v75BAIDAQn4AgwJ7wL//gH8AAf1+v8H+AoAAgEAC/n2C/X+/QQDCO/2CvgN+QAHBwAFDgP9BQH9/Qv4+v3/C/MIDwD2/gcCAPYDAwMAA+8CBf0CAwMGAvgC9/kAAQr1/fbyABMBAQME+vz5+QMF/PwAAPz9A/4MB/0ICPYLDv//8AYB+vT+AfzvDfIADPsCCQXvAQsKCfj2AP4G+Av+Bf/0AAD7A/f//QvxBAgT/uny/v3h9gH/FO4FAgwP9wkF9f8G9g8A7fTqBAERDgEC+AUE/fr46AH/CgLz9/399Qz5/fwH/P8H7/MR+AL+AwPt/AIJ8PsA8/zv+v4LAgwCB/v79wH7/ATzCwQBB/v9BP0D+fjw+P33Afr5CgL0/fv0AgD9/w4CAAj6AwsA+/oDCgEG/QT/CQIQ+f0BAvcI/w36/Qb5/fsCCAzzBwYJCf79BwQH/gUE+gIE/wAEBQf++wH7/f4ICAL4B/4FAwn5/f8G+/0DA/n8BQYACQUFBwQH/gEF/QL98AX++fj8BQAF9/oC/QMACQH+/gEEBwIH/AL/BAr+9gX++AQD"],
    ["anaphylaxis","health","8/X3EPfq+Qjx8fYEBggC8gf4EvoJCfgBBvMUBgfj+fsI+AcCAvEE/gT4+/cF+/0BAvn8AA/58wEKAvXn/fIEDvf6CQoJ+ff9A/gD+QMG6e75BPYNAwP99AcFCPoE/wMABQn7AQP/BgMC+fwEBQwC/fkJ+/PzB//v+AgEC/b9AQkIAQP4AQoEA/v7/hIEEP4G/P77BQMC//v9/wf2CgkG//0BD/sJAwT/AfcBA/j9+wD6/fwGDQUHA/r6/voE+////gEEAfcJBvb+DQAAAfsB/gQNDwIH+QEK/wQD+vQADAD7B/4EDfn6/vj3+v8D+gP6A/34//0OBAMD+f8BCgILBvLn9f7w5gUS/wTlAv78EvsE8wsCCwkC9v8BBgL+B/IGDPcB/Oz4BAoRAfoOAvoNCwMD9AwCCw4H9wYA6Qrz+gH8BPwCDv/3Awb7+QbzCPD+9wj3CP4SA+wFBgIGDwgG/gISDQAE+vcC+wT++wb+AwoBBvn6/AIMCv799QH/+AMABQH6APj9BAD0AvYC9gH9CAP1CgjwCPgBCAgC+Ar5/gf7CgkBCgAG+/v7/PkADPr9Bf4B/gX4BgQF+QABAQf/8wAD/wj/BAUAA/8CA/T0BvsDAQkCBQEA/AEIAAT6AQ0E9AIJCwX4/P4FBwj/AQYFAAX79vr9AgH9BgQCAvwGAP0D6vr/8OgICwP26QAHEBQDAPYIAg0E/e8ACfYICv4E+RP1/wjz/P3wAPz5/QX1DgYGBvH5Cg75/wQG//EH/gX7/Q0S+woF+/0B9/oE9gHv/wkB8QMQBAf3Bfj/7//7/foCBv78//vyFf0ABPwA+AoBAA/48v0IAgvz9PgK7/UC/wMCARAE/AT2/f4EAP8JCAT8//oI/AUJA/v4/AgNAvj+9wX//f8H/Aj3Bf8JBQQFBQUPAP4HAQf79/wK/P8E/P7+CQn//QMJ/wYH/gf5+voF/woK/QT/CgQAAfr5BP0JB/gCAv8B8gH9/PMGAgL+BfsA/vn0CQz8/wj/+AT9AwX/"],
    ["choking","health","7f/2C/Lj+wn1+vX98xDzAQDz9fkKDf33AP0HDgH77voB//3+BfcHBwcG9Qb6A/gR+wD0BwoHAvsE/Qb89PP+A/wDAP4C/fYACAPvAvX47/X8FvsH+Qr59QcFBggNBwIGFAz/AAf2Dfz+A/4C/P71+ggD8u3wAAb6+A/1Cfz6BwEPAvP8Awv3/fALBQQFCQUE+v4ICf4DAfr/+gD3Aw4GBQEDEvYBAv4FBQIBCv0K9f77/foCBgMIAvb59gz6/AH3//n4/QIJAvf3AP/7/PkN/g0LAv0AAf8D+v75+/sEAQT/AgP/Cv/4/vcGAQAEAQIBBP/7DwED/f37/PoK/AAECfX89hL0/wQCAP4D9vf2/+vtCQPxB/P09w32DAb5A+/17v4G/wQDCAj+7wL++fT7C/4P+g0NAPP+AQ7//wr1/wcL+gYHCff9BxD6/AEKA/X4B/sL/e4R/Pv+BgAEBAP3/Q0JAPoF+fYMCALyA/YG+QABDwgGC/z2Dgjs/wL0BAbyCPYB/wEE/ggBDAMDAQb/CQr7Cv0IAvv/+/n/+fUIAgL+AAn9BPsLBPv69v/y//jp/f77B/wJAg739wf/+wYPCQDwBwP9/AL5Afz8Bf/9/vsCDv38AQUE+/4JBAH8BwT59AEAAgoG/gP5/fL9/voA+wUFBgP+AgoDCQH4BP/9+vzy8vsI/QT8CfoKAPcBCf0EBf0BBQUM8/YMBQ8J+fLqB/0CCwEAEv4R8v/+FvX3DRAAAeQICPz8++8C/f786AMQ+PwABPcA/AYCAQUG8wD88AMM+wL4BQEG8AERBAf2/RH/+/j38fYK9/0P9wQI/AQD/v/3+fnxAAMLAfYOBvEB9wQB+gP5Ev389v3+9fz+DgAI/goBAf8E//kDBPT++f7/AfYK/vkEBAMC//v59fkA+P36+AEAAQEH/Pzz+P8D++/6Af0FAgwB/vcFAAH2/QcAAQMEBAgB+P39DvoE9w0A/fv6/AX+CwH+/Qb3AwX7CAIACPMB9QAA/foC/gIDBQYD"],
    ["cold-exposure","health","4f8NCvXu+/L1//L69QwA8/EEA/z/CAQJBvUC/v/5CgQFBCD+/QMIB/j/AP79BfAJ/PL9AgX8DwkDAP8M8QIK8fUKCQcE8//28v7xBAbrAhAABgMB+QH9/Pr7CvcT9f3xAggB/AgBAvn49wsBCvv/9gEAAgIE+ATzB/oADfUB/vwA/gb7+Q4P/AIHAPkTAvEF9gX8BQQMA/z9/AUABf3zBgv9BQgBCP4CCPvu/g32/vUC/PkGAf/8AQUGDAADAQEJ/vcB/AkC/QEC/QADAgUA8gj/CAEHAAUHAfkBCPL+AP72BPr//vn8/gH+Av0ABgH79QUB/QD5/wr77gP7Cv0DA+z++wz/9vz2+vvm9/kGAvb+B/8A/QD//Pn5A/QM/vcLBAoP/Q35/vXtAgT89AABBwbw9wz98QL5Dwr4/gYCAwEO//cCEfL9BAP++Qb/7Q8R/QQOBur//fX/Av359QIBBAAA+gT69PoE9fn//f0ICA39/gj0AP36+Pv88/wC/fr6BwUE+vQNBwnxBwP5B//1+vQB+/v7DQEEAPcHAgUC/P4MB//7/gEF/ff8/vwC7wb09/D6/wUQAPT0AwQEBwn7AgLy/QMA/QQGAfkBBQQDBfkQ/AwNAggA/gYB+PYEEvUGAgH8+fz8AwP5CA0H/Pv+/fv9B/ULBAr59wIEBgb0+wPgAgcM+/T8+vj49P7tEwH18fv98fYC8f7w9QMVA+4DCQv+EPP6BwoG7QoA+wkD8wX9/fb7EAcOAgr/9gbrAwz6CfcH/gT/CvgGA/cB+Pf/Ffv+Bgr/A/X49v4C6gf3+/3+AvkBAfL/9fz8DAwCA/wF/QP6/Pz6++7++g4JAvcD/QX7B/gADgn9AwYCAQH9+fkDBf4L/gT6A/kAAwUEBAEBCvT4//4IAgoF9vv8BP0CAf8G9vwAAvj8AQb8+//7/foC6wP+/foEBPsB8/7/+v8ABfr9CwIMAwED+v39+wT+APb7+AcEAgQA+Qf6AwT59ggDDAL9Av4JB/T4B/8K/QP7"],
    ["frostbite","health","8ubvB+wJ/fsFCe798wUK9PoIFQkC/gX78fT5Afv6Awj29hD7AfkD9PgFDwb7+vgJ+PD4/QP9Bv8DEQwA9Q4E//n2+vf3//b8A/j9AAHv/wP/BQL89/j2APYDBPQN+Pb3+Ab7BQUD+f31+vkB9gADDPb1+fcQDhH0BAD8/QUE9Ar1CQACAfwL/PgS/gMDAPr9+AYM9/oFBgsE/f/6CAX7Bg/+CQL4BwP8+wD98gsDA/v6Bfb6Bv0FAQoIBPwDC/YA/vwA+AH8CgL6+wUC+gH+/gP4C/4FDvr/A/oB9f4SAwICBPr/+/z8/fz//QD++gH7B/0J8v/+AgH1/e/5//gP++/r9AH0+ATw9PIA/AD7A+3/8PP++AcJ+fLx/gcCAvsMAPcO/AwCCfgA9vj++AYD+vXr/gP3/gIEDgoHDvcEEQb+AwADCf8CAP79AvH77vgJAf0D+fQD9vP6Avz/BgHx8fsE7v4F+AYD/PYX+P8JAgP09Az8CAcMAwL7Au8HDvPxBBQC+/0DBv79CwH/Bf8GDP8D9Qb7AwACBv/7CRH2+vUK/gf2Av7++Pz+B/sH/AP/B/TzAQf/BPcCBQYBBQD5/fn0BPv3AAT6Af//CQEDAfcBBgkKDAQHBgT/CvQB/PoD/AAB9Pz3+QMCBAMF+fr//QIA/QAF/wr59Pf9BAgF+QDp/fQL8e0A7QH+9//7CwzsBQ0N//wKBA/+9AYBDwcACQoMDfwAEQD5BP3oA/70/QH+9wP+/PIJBhH+/gD39hEC+/wBAgb19vcE9hH7CPr8Bfn5A/n59/75BgoC8/r8/vMD/e8ACgP6CPX8EfUI/AL++P0NAw8E8f8A9Ajy/wwG+gcKCPwIDgkC+Qr6AgQH/fr2Av8O/Qb9+/wEBwcTB/AHBf/8AAYHAgT/AfsFAvwH/QT4A/r7A/4HA/8CBQkK+wv/9woA/v8ABgkH/AcG9vj6/AQECA0HDAT/AwD7/Pf39/QJAfkK/AYCAvz+BP4CAf75+//5BvwE/f33BQAJBwH+"],
    ["heat-illness","health","9wABCQr0/fr+6v/8/Qj/9wT/B/7zAv4K6PwU8PoAChAJ//oD9fwG/Pn3BBn1BAf09wP+/vPzA/MGAfwDABAA8AkG8QkJ/PwEAwX0CgjqAAX38fj/BQz8/v/6DQP/APr/8f75APYH/gn1+gEKCf4MBwf3/wnv//jy+/71+AT+AfUF9wMP+gIEEAMG+wL8/AUG8vb8BAkHDAP++QH8AvzyBPoF+/z7CQoEBv76//j9AAT+AQcG9fUECQYGAvb5+gn2/wH49Qj5CwEGAwIFBv8GBwkHCAUEAf0A/v35BgQDAe8H//sI9e74//4ACwX7AQn79f8D+vsDBvP19gD3BPoAA/Xy9Qnz9Pb/APD//vcBC/H/BQEJ7woQBuoG+vQH/AMCBO77AAT4+f/3+QMQ+gT5+hTxAQj4+AcD+Qj4AwAD+vEACQEA/v4A/Pz99hP4Af8CBPMEBwkA+wfxDgABCQQB/fb77g35DwQR6AAK+QX6/f0B/vz8BgYF8gkD/e4DAAH7BwYDAv/+ARD3//b8DQL//AQABQACCgf+BPX//wIB7gARCAMA/gQABwH7//f4/AcAAgMP+/wJA/35A//4B/kECv73/gICC/4C+Az7Cw3/AQECCQgCAA0C+/0B+gb8+PXuAwHvAP39//b/+vwM/Qv//fn9Df4FAPX4+fj0+wj3+AbnBPgQAfQH/QTz7AwBEwMB/AgH+uX7+g36Evr5+wP4DQX5Cwf7/vsO7f4HAAP6BO4NAPcECgsI//YA/v3zDf/4AA4GAAYKDhX6/AoR9/ID+gUE8/wDBvP99gL68AECD/oG/fX3CPn7/f3+CvsC+PwGDgIIDfsH/fwP8v/2Af/2+P4AA/0HBAkA/QT9BfoT/vkD/v0N+QMABAL4/fEH+vYB/wQD/gMK9v0HBAEEAvX7/wf8CAACAv/09vkKBvP6+gcCAggD/wMC/wgD/AH4DQQBAvICDP0CBv8EAgME/Pn9+gYC8wX3+PkE/P7+/AT49AIF+Qr++fwEBv3/9AUF//8I"],
    ["stroke","health","4QYFDgHe/fgA/wMDBwYC+f7+DAX79/n/CusGD/ICCAgAAP0J9gAI7+b/ABD8/hAFBwf6B/v7Cg0GAQYC+f8D/wT8BgoA/fzx+P0H9wXv8wD9/fsAAvv8+ALvCvgDCfv5DQvs/gH//vQDCA0GAwQABAsFCfYDDADx//sA/QD8+QMIBvD8DQUF/vAA//wLBwP7+P77CQP9/vILB/n7/wb9CQL78gAHDgIJ/AQACwgH+/v6BwP8DP0I/vwCCgr9AQD4Bf75/gb7/vz9AQEG9Qn/BwUIAQ4HD/jzBwH2AQIB+wD6CP4B/QMCCwkFBgAC/vj1AgUE/gYL+gT2+vr+BfwAAOoK9/f+8gkJ/v396Qb5BPIGBwMB+vDsAgX1+g0D/AEGAwMDEvUF/fD+8w0G+/0CDRr5+QUI+Ab79foFBfwCBREHCQQIAQD6AAr3CwUD/P4C/Q4AAwEB+P8F9/gDDgMFBAcHBP/9Agz99gH59gn2BgsA+A3++hAN+PsF9wf6Awb+/v4H9f0KBPIFBAICAf34EfYA//sDDQLq+QIHBAr9Bgj8/AIG8QAGAAgH+gr/9QT68v0CBPMM/wH5Cwf+9PoEAvz0AO8ABAP7AQL4/O0BA/8LCgwE/vsB9v0C/f7+/AkLAwIA/fwC/gL9BAUBAfQFA/35CAH4AwUE9/YOCwAMBgneAgv8BfMNBQD/+Pn29QID/PgI9/kF8wIK+gIF9wP9//kKBP0JCgn3+wwBDPgAA/cA8gAS9e7u9gQHAf7xGQQGFP39/QAF9wL9APv8/f3///YKAPX59u0B9/sC7w3+/P4L//wC+/cL8QER/Pn5EA0RBAoG+vwCA/798/wEAwkCAgD/AwMLEgX+AQMK//oAAfsCAwD7/Pv7+QL9BvEH/AIE+fsNBP3+BwQH9fQJ+gvuBAj8DgD+AgEB8gIND/QD/wgC///3AAED9gH7/Qf9/PsDDfv8AwkCBgUDAfYJ/gIC+AYB/f37/QEEC/kQ/Qb2CAL5/gYDAQL6/Pj8Agj9CvUC"],
    ["heart-attack","health","9vz/GPzj9g/0+PcJEQ389gj9Dwf9/vYT7RQH7PL+/PsC+QkFCukC/QMPAQAICAkDAf4JEwMB+QYBCAD4+vYI9AYEBvwG8P/////8Bf8I8wn0AgsL9Q7y7wITBwD9/QX8AQjyBgQABA0BBAb5BAMAAfwBBAH7/wv3DP4K+gXzCP0N/QP++/z/Bff4+/4DBAgB/P36DAIA/Af58wYKAAH3CP8BBvD1BPsCCfoCAPv8+Pr49gH8A/0AAfv7/AABBAf3/fgBAw70Bf0EDgT2AAYA/wcDBwb/CAD3+/z+/QABCf0AA/oKBfj9+wkAABEBCv0B+vwG+wEA/gH39fr4/wUDAfn89woD6wEG8wYJCAMF9/AD/wAC7wf7/vr+AxMBAAb+AP//BhftB/T+Avv/APTwBAX8/xbyAPj2BP7yAP7oBQH/BgHz//L09AoEAwoGAPT97/n/B/EF+fn+CQL4AgcEBQcB7wIKAPwVBAYEBvkACwIA/hL9/wz4Agz8BPb8/gHvEAMI+wYH8wj9AvH7BgH+CAEB+wMFBv3+/gEECfwHAf0G/v7/Bgf+BwMNB//7Bv7r/foB+gf+BgP6+wUD/ggFAwT3AAAF+vgA/gP1Avv4//n7DQYGDgf3AfoKCe8BC/kE+wz9DgkEAPj++gkFBPH3+vrzAf4MBPz8AAP4BggC8P/xAfcBBfL4Avn39ggLB/wM+/wOBu8B8hULDxPq+PvrAgfzCwkM/foW9Af2A/z8/QP5EAoF9Qvu/PUEBPX8/P4KBAkQBAD/Avn68AIABwXs+fb/8xDx++36+AkG+Av9C/wAAPIBD/v79gH+BAj9+gX//wH//wAJEvgD9gr9BfoCAQcH//sH9f0N9AUI+f8G+QcB/fYGCAQE//z3/AkE+wX+A/0I/wIICP4HAwUD+gv29QL8CgQH+gz59PkDAvv/AfkJAAT/Dfz+A/v9BgH4AQQCBgAFCQIOBf0BAQICAQMFAQIH/QANBfP5Ae78/f0FAvkEA/8D/wIBBAH4/QH8/wIB"],
    ["resuscitation","health","8hEDDwfm//j07OwCBP35BAMCDwAGBvMN9QEE/fIF9AH9CQz9AfsJBAsRAQH6BQMJ7Ab6BRIBAP4J8QEF7wUECgUF/AMC/fwH/gXo+gT5+PkAAvoA/BT38wYKCAgK+wP/AAz+9gb1DvYFAAgKA/n++AkDAfv4+wEA+gX8/QD8/Pn+//v+Cv0FCPT/9wISBPsDAvwDDfQB9/sE+/33+gUEAv0KDv38EAwIAQTxCP4H+v/2CP0QBPcEDvb/CgHt+wf0BwIB/wf6DPkDAwEC+fgFAwwE/Qf+Avv3//f8BPsFAvr+/wUFC/zu/P4AAPn/Af8A//8ADwUI//379vsEAwf/APwN7wn99P78/uH1BwMO+/PzCwH/BfQDDAII/ATyAfj/+/YMBg37AgsKCvj/A/oCBuz/EQcH+/7+A/QE9vb/8wf8+/wEAvsGAP7u8/7/AOv2/vnz9PYC+gX7BQUHEvQTAAL+9wcX+Qb49/4K/PXu9fj6BAH7/wcC+/gHCgHx//v3AP33+gT8/QL4+wcAEQoD9vYIBgX8BPb8B/v+9PYPCgEABgQD//n8AP72+gECCf4A9f///AIH+gj0+AwA+fz4BQH/AP0HAwDzBwYGB/j1AgQDDgP8B/sD+Pb6/vr2B//1AQr4+gj7+AEA/QAC9/f3/wn8AgMGBgT+Avn+9wAGAQvpCfMFBO8CAQXz+/f+9v8D/AoJ/gsL6wL6/AP25QX29/cDCAcZCAsW/Ab2Bgn+DA78+AcBAwT89fUBDgT97wIH8g4G/fv7B/wABPL/AQTz+Bv97wXy/gYC/AcBAAfvA/cB9/f4A+4B9vj8+gD19/7zB/jz8vwC9AD+AAz/AfwI+gf6+/wBEgYKAf7/AgICAQP2AAEFCAP9AAL09Pn6BAYNCv////UFAPsI/f4HCAj//fsDBQAJ+fwH+v0BBQMDAAH8BQP5//oD9vf5Cvr5/Q7+AgD++wH99gP0APIB9/z8/f78/wL9/fT9/wIADP8F/ff7AAH/9vv5+P8AAwIG9AgG"],
    ["unresponsive","health","8Rb7AwgCDf0E8vQE8gMA9+8CAvUPAgX3+fsBDQkG/QEG8wMJ/AUFDvwE+/7++P/++BAJ/wEJAvbx6/v4/RQB/PQIBwr2A/8FB/sA9vn+8QsIBQoA8/EH+QUC9/b7+QgC/wP3/gUFDO7/BhEM/wr8Dwf55wXpDf4L8PwL/wUD8/oOB/38BvoABwH8/wj9+AQCBgwF/vn/+QYA+w/8CQME8ggI/v0CAvwAAPoB+AAA/QH8/gABAvj/Awn/AwAF/v/6BfIE/QHwCwUFAfcI+/YEDgT0+f4JAAf1/PsB/PsI+/0F9/32/v0G/AoCCAUF/vf5AwME/vgACPf4Avf5AgIED/4A9AHv9P7zCN/u+/35A/cGBwP+DA3xBfP3DQj+AvsB/voCBgL9Cw0KDAEFAgT5B/UM/woSAv3w+/z8AQXyDxAADP8G/voEBwP/6/z+A/EDCwP2AwULBPr2B/gICAbz+wYU+voM/Pr6+gH7/Abu+gL9CwALAPj+9wEGCAgECfcAAgf69voJ/Ar+AvkDCQD1CPz6AQn8BOwAAPoD+PcHAQAEBP/9BQD9AQT++gD9/fb18QgAB//+BgH7+Ab/APv9/AH+BP4I+g/5Cwj9/f/uEAH7CA77AAX6BPb2AwgC+/z8Cwj/DAUE7/38CPcD/gv5BAb+/QwFD/73/P/8+f759gPkCgQJCuz9Cf7w8wYFAf3xAQgG/QX8+g0GBwQF9fr++/r+Gv4KAAQA6wAFCgH7CfzxD/ED6+4FCQT+AwfyCQIFAQQEBgz89vIB/AQH9/QFAQwC9/j89PL9Ce4V9QP4//wAC/IA8vwKBv4QAPn4APD+A//09gEE/wcI//QK/wP9APz/9wEEAA/2CPoLAgsICQsBEvr+8gMPAgYABP4A+ggBCwD++wIAAv4F+/j8AvP4+ggFBgYF+QD4AAAMB/8C/fr5+AQC/QQF+QAAA/36Bwz9BQD8/wH8/Pz7/gH+/fn99AEB/w3x/gICCv4E/wfz//YG+/gCAv4LAv77/v4KA/4I"],
    ["swallowed-object","health","6vj3D+sODQL9Dgr7/fD6D/oAAv37AQX2DegGA/cAAvD8CADr++IACAMBCgz27QIL+wbzAPcB/BEE/w/9+fT9+wgFDAQG/P70EwT0/gsA+fQD/QP6AQUNEQn9BQYG8AD3Af8B7gXzEvUEBQEIBPj5+vME//73BvoIBvsFBvX6Awr6/wgA+AQGAAQJCvsEAgIG+fMD+P72+vj59/7/ARP6Bfj/CPwK/RAB+P/+APgIAPsI/wEHBAP9CwAC/AME/voJ/P0KAg8C//v7+/r9/P8EBf0B/vb2BgMG/QL6+PoFAgUA//8IBgEA/PgC9/YABQME/wADBAMEAwH/AwP9/vUCAeYD+Qz8/g8G+Pj18Pz38f0A/wXr/QcT//z77xL9D/4JBA0G9QX1EgEH/gQJ/QPnAfoE+ADwAP8EAQgQAvv2AwYPAQICAvYA5fz6+QQGAfIC+/0D9/EMBw0HBAoLBQQGCwH6Auv++v78/RH7Af4D/wgE/gYO/QTyCw7uAfjyBPn4AwYA/PoA+RD+AAwEAQEKCwf6CgT///75A/0J+//8/wb+BAb//Pr7//ryAvj/AgXw/fMEAAUE9QsA+gIAAAr+CAL0DP4AAfr8+wP/Cfz7A/79CAABAgQKBw4GBP8L//n9CAUG/v/69wAE+QUEA/wF9QUH/fj5BgX+AAf8+v8D+wn3//gD7f0F/AQHBAD7+voJ+QMW9gcW/vr9+An5BPT49v/7AP//8QsB5/z1DO0B6Qf0CPQHB/YF9vz7AfX/9fQFC/4K+v8DBAga/f0K+/r9CfD++v74AwQTCwUA8gz6+/oKBhD7/fcA8PgI+wkKAfsJAwH0/fTuAgANCPoLAQYFAP4I/AkDEPnyAPsCCf//AAAAAw0DBQkE/P8C//IDAvL8A/UHAP71//gFCPsHAQv8AAMHBPwM/QQA+wII+/7t8f0FAvgIBgQF9/cIAQEICAT79AL5Av35+gL3Df/+CgH9CAAB/AH/+/v++Qf8/QYH+gn1Afz/Avz6BQf8Av4DCP38"],
    ["ingestion","health","5wP/Du7m/RES+Pz4AggAEggFEQoHAgoC/wH/+//++f/6C/0G8QUTBgPu//r6BwUCBgAL/gUC+voFBwbw+vTuAwARAQIU/AsMD/0D/Ar7AP8C9wIC9QkLBwMCAwMF+//6Dv8E9QD7Be77Bv4C/Qf8+/0LBewC8Ar2//j1A//5/wb7A/gE9vz9A/T7BwUNAggEAQEIBwMC/Ab+/Pj/+wf0+/sHCQz9/AP9Agj3BvwC9w8FA/b89gMACwD6BvcD/e4HBP/++goG//gCA/z29v4HAvsLCP4D9AEN/Qb9//kBEA0C+QUC+/z+BwMK9vz9AfoBBgf5Bf3++wcD8P7z/gAG/Oz06gP2+vQRAgL6/PkJ9Qb8Cff26w7+9Qr/CxIE+fnzAwn9/ADvDgID+//y/+v0/ATy6AP9AgL0EwgK8fntA/cJB/r5AfH++gIN+AALB/YDA/8B/P8OCPQO//n+Bfz8+hL6Af4L/vsF9QQCDgT8AAL3BQ3z+QH8CBDoBvjzAf/xB/34AgEGAAL7Awz2/wMFB/H8DAMD+fv//f//CAAGAQD/BgMK/QQFAf8E/Ab+BQz1AP3/Bv4C/wD7AQn6AP74EP35BgH8BQD8+vj2/Qn89v/0CgQDBv0CCv0I/v77/AQK//0A9gP6/wH+/Pz9AfgD/AECCvwHDQICBQQBAAIA+/739e8A998EAP/99ez3AQ0QCPkH8f/6DgAKHP0E+Pz77Q76BQbo/wT8/P4FCgcHAwz8DvzxAAIG/AYCBgb99wIC/wP5+gYBAAL+CfwDC/76AAXz9goIDQT9BQIF+AoCA/wLBQP38vX99/0H/QH8DAEK8vwK/v4BCgL/9ff8/wj3A/0AAQYKA/b8+vwPCv3/BgH4CP8FAwn2BgL+7/8C/vz++AkLCP/4AgQGEfgLBg7+Cv8IBQcN9wD/9fcD9vgIAAYTBgoICP38B/z6+woADQYBAvYHBv/+AQD7AvsF+Ab3/gUJCAH68fkIAQII/gcD/vII+f7+AwT9AgUE+f799wb/"],
    ["snakebite","health","A/n3Du/wCe/yAgIG+QP69f4GAv3z9xIFDO7sE/Lx+fTy+PbrF/3/9wkC/wQLBw4IBgEI5/72Dfr5C/QA7+0A8v/8//oD+/r88wb+Awz6AAP8APsKCQ0A/f77/voJ+vn7/gIDBwP7CP0JAQz78/H+/PwM+vwGBv8CAhD87u0KB/n98wkG/vkB/f38AwYCC/368wABCv0FAfkAAAIBCgQB/goCCQoBB/cDA/wCDAMBAgn8+AH3+fr99fv/AgP6/fYB+/v/AwUB9P8CAv0DDwD8BgcG+gn7BfkEBfgDAPwBBvwE/P70/QT6/wMB9wD7/wL9/gML+An2/gX7APj5Bv38B/Pi+BL97ATn//QSA/r9+/AKAAn7AP8LABPx+wv1+PnzCPf9/f8NFfj7+AD3DPv7/Av4BugF9u36AgDwFv/rCv/6/v32+/cC+vQPAfj3A/34APr8BRQQDgH+/An6AQMGB/kIDQML9A70BgIC9/X//f8BBAMC//4A/QUT9v/w/Qf+A/8HD/7++gIF/gABBwMDAfH8BPX4AwD7AgUB/gz/CAEB/wQBBAIBAQIF/P76AAT7AAIAAP4C/fkACgAHBf3zBPgG+PwFAPYB+QP7CgECAv0AB/4A/AP4/gQA/QEN9gIMBff9/PoA/wL/APsB9voGBAUCB/v/+gYBAwP0AwMB/wD18PgF/+MA9O79/hX5AfzvA/wG9PUHCwYT6vIT+f787wPw9foH8Abr++/++QL7Cw0GAP/x/AAB/P4T+Q7y8AT69v3+Aw788/nqCP4B/uv/+w0B/P4ICwYBAvYC9AD/Afj7EgYDBf0C+QgGAQT1+Ab+AAYD+P7//voEB/f89PsI+gkA+gkBDf3//f0ACwoKAAL0BvwH+A//9Ab9DQETBvn7BAUGCAYE/QQAAP4A/gIEAf7/BAICAAX5AAMEBQT98gf+//kB/gP//QIQ9AEBAvr2BAgE/wAF+QAFAgX6AvkJBgL/AQX7+/gE/v38+/n5BAICAAL/APz+AQL6/wUK/QQD"],
    ["animal-bite","health","6fwGEAHs+wUF9gML/AD1DgYODwEDDAcBCPv7BgQC+gT9/vf3CvsG9xn08/P+/wAH9/YI/AX0+/n/GAD/A/b4BfoIDfT7AQQBBf779vj57w0HBAcE/gP/Ev/2D/j9BvcO/wsNBQICCgL5AAH89fcMAAUJBvj8//PyC//3AAX1/fwEAgcEAgoA/PnxBBT+Av3/AQD6/wUI9QAFBQcG/g0H+v0GAgf/AQAH+v7wBgQE+wkABfzv9QEF+wcLBvUN9fUG/vr18wUEAPcKCQMF+PYL/wgHCv4K+/4VAAEDB/QFBP//BAT2/gYECggB/f/8+fn+AQv2///7/AME+Pv+BQIHCOfrAQv36fb39fcGDv/3+wsO9QgI8gMK+gHq+RUDC/UGAAX57Qv5Afv59/cB7wcA/PXoBO74A+8DAA0B/fz/AQP+/gQD/wIA+v8I8PgF7QQMAgEAAwoE/wEFCwIJDP37/fT//vj9/wH/Af0N/fTy9/UCDgkG+/X4//z5///x9//4CP0DAv738/z5/wcA/QUGBvsA/AL+AQDtDvkA/Az98Pz8CQYUCv8FBP0E/gD5+gQE9QAJ+f0C+/8BBQX3/vr5DfYE9/0A//8HAgX8BQL5Af8OCAEMAgQMAPz//f4FBfT7AwL8Awb6+v8EAAT8/Qn9DfcE/P78Bv4H/vwB+gQJ9QXy9/wT9eoFAf0ECBUEAAz4EPrpCfYLDv0K8O0N+wnvBfAGCvsH7xT7B+7oCe8EAwrz7w/99QcC+AH7Afr++gIEB/f6AQEH//b99O8J8f3+BQv4CQAECwEC//8H/QkFA/n3BwEKAQgNBwH2EAgJ9AEH+wEO+/8CBf/6+/cA+AcA7wD8AgD2/fsA/vkC/gID/P/9BPz//f367wj4+/sIBAH8Af79DAUODAQABPn9/PkDA/0HA/f8Bfv++wP6+QX/9gb5BPwBBAL6BP4D/v0A9wX4CwcFBgMJBAgB9vkB+gT3Av0DAwT9A/n+/QIH/voE9vr6/AP+//wKBAfxBQAHAgEI"],
    ["insect-sting","health","9/D9A/ztCv8C/QUN/wMG8woDCQUU+gn1AAH/AQf49QcUCAUI/eoR7vjoBBX++vQQCfoH9/z69/D/CwH+CQAI+RH4BfYL+/bs/fgDAv4J//H5+/3+DP0A7BAE+u8DEgwBDAAKAPX3/f8F+AL9EAEQCvf8DPoCAf79+QIE+QPyCfwIB/sFBQ3+BPr9AgQICfwE/vf7APv//v70Bg8FEAkC//39/AMF/P0K+PkE/gEAB/sA+AMCBAsC+gQKA/8G//gE//0S/QEE+Pz3Dfr7+/3/AQMFCQcA+v4FAgEC9AH5/wkABv78Bv/5/f36CAME9wP+AQL/+gAH/gECAP7/CgcHBPPmAQYB9/nz9vwBCfwDAeP9+gYADAoU9wMB9gkS/u4LFAL9A/nsCgEB7/77/QzyGP/2APz79P34//oB9gcD/vv7Ag70DPf++Pny+fn68vsEAPULABIDAeoE/PkKBQYD+AgMBAH39gn59gAB9AoU/AX59QQA/fUC//4L8vsK8Av0AgcDAAEI+QEEAgj7AAcFCQL1AP4DBfcE/AIM/w7+//8A/QgCBAb5BwT6BgAE+wMDB/kD/P0N//0MBfUC//f5AQT0AwQJ/wEF/gr8+wkCAPwABwcCBAAF9gAAAPv7/gMHAAYB+QEC+P4CBAwEB/oI/wX/9wH9A/wF//r1/QMDDgTw6QAS9fEA/QbsGAv6BAzqDAEC/gkQDfj8+/wDBPT8ERINCQP58Qj89+b/BAAD8wYG9QT1//j2Bf389PT6+/3/Ae8Q+gz5+usF/wcF9QL9/P37+QwUAQH0Df4C9fn9/gAI/wTw9/QN/v30BfEKAwcL/QASBfwB//byBAn39AgDAAkIAvsKCAEE//UGBgIRDgb48voHAAABB/v++/4HBgID/P/8AgUEAP///v0AAPsFAwr+CP0FB/8BDAH7/Av++P/8/AYB+AP//v0N9gIGAQIG/wP9/AL///4BAQEK9QAE+wL9+f0D+/kA//4HB/4C+/4BAvwCBf8ABP34Av3/BgUF"],
    ["newborn-fever","health","/e/vAvr/AA398+sE/AP+9/MN8Pz37f787/ADC/z9/goFBA/9Cfv/CQP8Evz9/uv4+/rzDPIQAAD9+QMJBAD7AwX0+PP98gf7Cg35BQn2BQAC+AD49QAH+/sD/Q4B/fj4Afj1Af8H/wQC8voCBwQFAu8GEvUSDPoAA/kD8/kEAPYI+fP49QICCvsN+/wCBPv/+/oD/gAG/Qb4+v4EAAgDAwYI/fkHAAb+AfgC/voKDPsAAwAB+AUBA/sAAw3/+v8LDPgZ8/8C/wX9/AwDBv8E9vwCBgoHDf8MAgcCAvn9AfYEAP4H+/cHA/n6/fr6BPv7/Af8DAoHB/j7CvkH9O35++vy8QD/6AYU//nlCwICC/8KBeP++P/19P33BAn///77BAsR9Qj9/Qnt/QAEAP75A/Lw8Qf/9/f99AQB+v8ICf76AAP5BvkF+QT6/wP/AvX9+wgG//vvBgIE/wH/+gD3+wcA7AED+g0B/vUEDvzy9/0HBP8AAhT5+AAC/vb/+P/4/Af4+PsD9w0DCgL1B+76Bf7++P7/BwkF+fsBDgUC+voABgbxBQD9+/Pt9/76AQf2Ag4BA/8DAQgC/wUCA//0CvbwCv/6DAkQ/QIADAMCBg0E+QgI+wr/+P0EBQH+BP/++PkF/f4HAwT//AQBAQb7AwT8//0N+v0F/wD7/Pb2+v/s/fEC9g0HBPz38vv4A/3u9gvzCf//Df3z+f4I+g389wkK//r38PwU8/r/D/L9/Qj0+gb7+wL//P4FBPsPCvf9+fv+AgT2+/QF/vwP9gAA9PwC+PP6ABL1+P7yAPv8Avr9/PX7AggGDPj8EAQI/QsH/vr1/AQf/vr//vgLAf4D//v8/fQABwUO/v79AwrxBAH+9wQHAwQRAvb5BwH7EfbwCv8J+QUDEAEG8fwF+f/++QQG9gIACQMF/vv8Bv8D+QsA8gP4AgYKAAQL+Az+9QkGEfkL9/4ECgUB/PoG/gf/9QjzAgX48v4A/QD8CAD+AAIFAAADBgL9/f7///j7+fsI"],
    ["infant-fever","health","A+/+A/j+Bg/89vUD+Qr1/P/19QDyAwT7+f0VAhD9/P0K8fwAA/YGAfz6AREC+PX2+ur/DvcCCgTz/gL+Df8E+g3//fsA9vn8CA34BwoF9/v8+Pr4/AYA9voEAxAN+/4DAPn5DP4HDhHt/Ar+9fr7/fUCAwEHAfcJBwP49QD7AfEI/PkBCAX7D/8J+/gA/vwC9gH9/wT/B/sE+/4ACgDvB/0C/fj9+AEJ9fIFAe8F/v76CAEBAgMBAvbzBA0AAAEHA+8OBAUF/vj7CgYEDvUEB/r/ExIHBvf8Agf/A/cBAe4IBQYAAfgC9vb18fQEAQD+Bvr+/QcJAfYCBPr//u34+vPv7/X0+AAPCvfzBvUFAv7+De78+Pb//ADwCRHzAvsIDAAMCAL97Qz3+P3/BAbz/PD5AAfzEPr//fwCCAcD9wQI+gP2+fIF/v4H/gkA+wHuCfkA7/n8EQD7+/kB/O/t9AgE+/oHBQL//vz3AQP69/T9DQEA/wz2/v/9B/75+/n8+/X5+/oN/AsBBgf2/wfzAwD+AAr6Af0E8fQFCAYP9f8C+P8BAggBAgL4+AT9BwP+CAUDAvsMB/r1BQMLAfYADf8EEfT9BQQDBP8OAw37BAkC+QUE/gP+CAEE/Q/7+AnwDPcB/gD+/wYC+/QA+gUBAv0I/A0EAwT+9wr79vLy/AIE/esH7/39BvX78fgBFAv89Qj1//31BPz87u4H7/oDAgEC/vz1+AEO+/kCBvkL9u7x8PQG8wIR/AEI+fYAAvT/C/v7AQbs/v0HAvsBAvgBAxH7DPYJ/xD7A/b6/wny+wQIA+nv+AgL+/r9+wD89AH/+gQA+Q0HAusc7wT9+P78AgT3+QH4/AUCAgv8/A76Afb++vYDAQP6Dff5/gn9CP4KAQQA9gYAAP/8CPwA+wQMAwb+8QAAAfoFAgIDBP38AAX9/Af5AwH5+Pv+Cgv6Awj+AgEJ/QYKAQUD8/4HAPz2+Af+Af73+wIHAf34+vUI+Ab4+/3+CwAEBAEA/v798QIF"],
    ["childbirth","health","+Pz///P7A/v18/AAA/74AgoS+AoG+vcB8en+DfIC/PH/CQgB9ff1DPz4BPwD9fMF+f75+ggC+P/38vf8CvsCABUNBu3//gD+DQX9BhD2/PAE9fbw+/oFAfYE9QT1EvP8DgQC7w32Bwb8+v8HAPL7DgMG+foGBfL6+gH0BwEECPn97/v7/gYJBQsK9fkMCfYABf7+Av399P78Av0I+AoCAf0FDvwGBgEKBwL6BgX4+/3/B/oIBwcKCPwGAAcCCwL+8/sI+QT1AAEDAgL6CfYJBPsC+gYGAQMHAAD1APn///YF+PsNB/UC/QAB+/77Dfn3+/38AAkG/fX9+AL78Pb7/OwI+wQG+PoG+fMACwD+6vwABfj5APX7+fIADvwHB/fvD/z4+Ab7+wn5/OvvBfL2DvIOCf76AfgE+QkF+QD8/gAJAxn5AQAKAwIECg/8/fL1/gAD+fMA/fwM+vP++Qn6CQXw7gQGAgAG+wAHBgj1AAwA+AgB+gYDBwcM9vII8/32BQcIBgoB9/b6B/vw//4C/Pz5++8D/f/6APkFAAYF/wUMBA73//7z9QrsDfj3//j2Avv5/AH9BAgLAQL9BwT5Af78+gP//PgFBgkQAfsEAAYDAwL79AgJAf/79wH89Pb1+/b7Cv4AA/oF/PoCAgn9AP0QAf4FAPrzAwQH/QH//fz/+O4FCPj6DAj18A0C+QD4CxjtAfoABP/z8goU8gn4+gMRBgT///kM9f8BBAUA/QQG//fx+QrzBfr//vf2B/MHC/n/7wUAAwUKAPoI+fcF7vP6AvX++v8A/AT6AvcC+v8S//X8C/YDAwH/AAn89/X/+QAC/PcY9Q35/vT/9vX97f4A9vb4BvsCAg3/9QQC/vkJ+AP3+QX5C/YLBAYCBQf8/QgM/Qb4/fzx7fsAAgUD9f8F/wYDC//++vwC//oC8AL2BAHz+AEBB/n3CAkF/wkNBwUB/f4BBP3//QAB/AcCAAX0AgIJ/P8JAgP8/vMK/QIE9wIDAgEA+P0FB/r27foI"],
    ["fracture","health","6wn5AAT29+T2Af4N+f4EAQADDAPrAQQO/O/zDAf4+gwG9ffyCgkJEgQBBwEHCQH/CP4I8PUD+QMGCOr8Aw/3AwEKBvr7CPsQ9RP9/v7wEQcC/Pf6Awz9/PwF+/cM+PYPAAb5/v7z//4GA/0BAv77AgID9PkC8Ab7//sG9AD1D/T7Dvr9BQcC+fj/Ef74C/gCAQEEAwUFA/YI/REAA/MC9gYNAwoA+/0ODAEDDPwDB/75/fP69AX1//37/Pzy+gQE9Qb2AAkJA/z9+vv8/QD3CgUB/Qj7/Qb+/PkDAvr9/QH+/wQIBAEB/QL9/ff2BPQJAv8GAQMC/AEGCfL/BQMC9u38Bf///APk/QQGBQvyCPkJCf34+AUCDQL3+RMGAAME+QPwA/v5EvkD/wcTBAEBBfsFCfIGBvIMBAf9/uX0Bvn7Bfz47Avt+f37BA8E9gn7APT89/b//gP88wPsDwQDBv0LAAIGDAAP8/sDAfgA8vcEAAANAgX78wr+9gcACvH29xT8BPkH+/zxAQT9EwX3BAAM/QkD+vkC9P//AvYB/fkC/f8E9wb8//3/+P39A/X7AgMC+gUG/fX99wUD/wMFB/b7Avf1/gb7CAQDAQTy/v8DA/wHBgf6CQH3//z9Cff6AP4BEAIB+AED+f0K/QH67/z6AvkA/gT/APn//AX6+f/pAfwE/fAA5vgAAA7+9wX7A/8MBuf1ARn16vsN/PkCAwAE+PD++fv2/P4M/gwCA/76AA32/wr6Bw0GA/wCAPcDBOwBAfgH+QjyEev9+OwICfbzB/H9DPTzBgIBABEB/Qb+BPz+AvQF/QADBgkC+/b7Awj/+/v6CwL5DvPy+/n/9fwH/PoGAg7+9gYFCQAIAAD++QUD/f4H9wP+Bv4HAgL9+Pz7CQMLBQcLDP0E/gT/DfT3/AsB/f739ggHAvkBCQf5Bfz/BwAHAv8A+A38Cv4JCQr8CwEBAfr5+fn3+QH89QTzAAcAAf4DAfkIAgb8BQD7/P0HAwb9/fz6+QH3/gIG"],
    ["burn","health","7fX/Ee7k7v0B8vr5/goJ9gQTAwABBxcECPb0+gD3CgoFBwED9Pr26+/s+w8BBhgK//n+Bfv89wUSBwMGBPfvAPj/Agf78fvx+gj3A/r7+wb/BwYBDAUF9wMG+Pr6BvoMBQ/1BPwK+gH6AwH7+/z0CQICAgkF+wL6/P7+8wcC9AQGDPT6/gIEAfUB9/sOCwz+BAQFBgEB/fsDCP38BQXt+wb5/QoIAQIE9QkAAgIG/Pz7A/v4/wT8Awf8BP0L/AEKA/z4AwP+/wIJBfr8Af/+/gcI+/0DCf0BCgcDAwn9+QD3AgIJAPn+CvoECBH5/PMC/AMK/wQK/gcA/Pn3CAMEAfb8/gUD+vv5Afb+/wQHBQUMEgUECPUP+PYM+fYK9w3/CvL3B/r89PgB/v7/7QYABQj3Cgry+wn2CAgCABYI+vQIA/kEBQL1BfQH9RMEEvYACucDAwnyAQkICAELCP4K+gH98wP1BvcL7QkF/gL5EQD+APb+AAwE8Af8+AQD7gj6Bf77Bvj9+QL+AAYC9wIH9gD2BQYCBw78//X6//kI8vv9/QEAAQQKDAIG9vj+BQcD9/7/AO8JAggBBP/1BvgJD/8B+v30AAD89QX8DAYDAwUHAgcBBvoCCQj9+g4B/wL5B/36BPQCAAUBC/gK+P4B+v35B/0A9/T5/Pr5+Qr88wPn/wERBef3/f3y7wP2BAQHARD9Efj9C/r2B/sBCvYOAxT29/kBAfzx+uz8EPH5DAUF+AgE9wQB9xX9BfwPBv35B/kF+An7/AICDPsZBA39+wTzAwgL9gb8BwT/+AEIBvz59fEABQHwC/QKCwQJ9xEJ+fsE+wQHBvT9+AP6/vcF9AoJ/wH8AP4A+v77BAIB/vz8+gP+Av79+v8DAAcBCvb5BAIEDQj4Ag8FB/YFBv0F/fUB+QL2DQQF/AQF+RD9BQf7AAb/AAL8BPwP+gH+Bv3+B/8KCgAD/wb+AwACA/0G/gMJ+QHw/v38+gIDBAX4AQH9+ALuAP/2AgQC/v0GBfYC"],
    ["bleeding","health","5PgEA+/o6f388/kXCwbzAPcM8f4F9AELBgQCABD/9/cG6QH5Agf9BAH3+wYE/g37+vYN/wYG/QIGAw8OEQb+APP88fkN/A4F7Azz+fYHAPMGAfoAAwYHAAwE8v/5B/f9+PYA//Xz+gAC/gj+6/8C//8K9wb8BP0JBfsA+f8H8gnx/AD+/AEL9QMOAvcI/vwH/v4C9wP39wkG/P4ABAD0AfwD9v0DAewOCPkBAPf++gYAA/kB/v0D9/0BDAIJ/wQEDP4CAP/6/wADAQLxBQH7DPz9/QYJ9wMACgYBAvMGAwAB+f8I/AL//fwBBv/+/QP+CgD2AwUA/gP3/v7/Av8G+fcS/xAD6vgEAA32Bw0FBgMPCfn8AfgIAQAGAQwO6+/1+/8G9gEVAvz7AvEIAgEJDAb0APYH8P0HAAgJE/UGAwMF//b9AQL8CO4K9fr9BAv++hMCBgXuBvgHB/v7/wwBAQUJAvsA9AYFEQQD/wEA//kDBPoL+Ar4B+79/gPx/fL4EAb9BPcD//sFEwj9DQL2+gMH+fb5C/EB+AcDAQAFBvEC/fz5B/72Df/4+vn+7wP/8g78B/sG+AT2Aw///wL8AQMD//0EAwMABvUA+v0HB/0P/f79AP79+gIC+wf5/AIDAPsF+Qb5CP8CAAkA+gv/AQj9+wT8A/YC9P78/vX/BAPwAwr6AO0HAAcB+RIG+wb+/QQE+/IHAQb7/v8GFe7w/gAHBAIKAAP3/fvsAPr6/vv1/QPuBwcC+wr+Af0DDvQHB/X8/g0G/QfoDO3x/AQECvv//wj6/wH8EPwG9fsD+wLx/wQB/fwE+vUNBwP/9QD8DAgADv36CQLz+fYD9/n48wQE+gMPCfv5BgECAQER///9AQMLBQL/AAYB++4FAQH6+/z6CAoDBf4FBP8O/PoEDfoAAfwE+fP6AggB/gbx9wX4A/3+/P3/7QoH8gIAEPUMBvYFBQrwCfb/BAcA/QXy/w0MBAD47wP5Af4H/Pv7//kMBPv2+vgHBgACCAECB/4M"],
    ["puncture-wound","health","6PwCDv36//bxD/f++P//BQYR+wr5+g8A9QX9/hoF9wgC+vz3CQcYAwby+Oz1/gz5/fsL7gEG+/wOCQUMA//z/Qf3Ae/9Bg3z+QUKBf0G+gX98AHyAAQD+Pn+/gMDAe4GAfAJBwoN/vsA/g38AwIKCQL0Bv4G+QYGC//+9Qv++/z5Bg70+v388/QNA/sB/AD5AvoBBvkB/PcEAQj6Bv35/vsFBwj9/QcIAgL0+wEKBPUB8P739AkBB/oG/f0HAQIBB/T7+f3//goBDP8A+ff5AwEEBQQH//sM+fwN+gj5/Qn/BwT39/v5CQABDPj+//gK/AP49wYMAwH0//8ABQQGAPH2/Rbw7APu9wUICfsK9wEDAQP79PsL6wIABQb59wQHCfn79Ab+CPQD9PQC+AsPAQME9PAEAf4NCw/5CvQE+v73/f/yAfn97Pr8+/0B+/sC8vwFCwb4Agb89gH+BgUDAvj4DAoKCP35/fkM/QD9/ggMCQMCBwf18gEE9fL/CPsABPwM8vv2AfL8/QH5DgX8/Pn7CAIB9u7+AQAC/AgKCu0CD/3+AgEGBfj68wj5CgoE9AD4Afj4/goD/wcABwL4/wb///8DAP/w/wj/BgX+CQwAAfb+/fb4DQb9BvsC/vYEB/788wAFBAMK+v0G+gn8AvkP//oMCfv+/voDBgsE9gr3AfYABOX8/PP/Bwv/EvzzCBfy+/MFE/P/+uIRB/wEAAbxAAYDAgz1+AD4BQP99gb1Af0CB/vx8gUAAgf18vsGAPr58/r2BvL6+vIG+v0D9P0E/AP57gf/A/H98P0UAgYB9gUOAPwFB/8KBfoI/voCDAUJ+/8F/Pz///b5/wEA+/78Cf8A//r6/QD4/AgW/vn6/gb+/QD8/wEDA/kEB/X9Cgz/AAXzAf8H/AL///0G9Pr3AgUDCfsE9/cF/AIF/hMA/An27/js//oE8P33AwMBAQsAAwT7AwT3BP0JB/wBAAUV/vf6+vwACAAB/AT3/QT4BQD+Bff9BP8HBQQBCv4E"],
    ["dehydration","health","9Pn/D+TuCRby7/fs8er4/fv/+wD47wn3CPX1A/sOBPwEEQf49Pb/DP/xCe4F6v/rAPr4A/T9+wYF/wYEBAD8BQ8H9vcF9wIIAQX29woL+QIBARb+/wYM+AcL/PzvBPb1A/8B///1Bgz/9Qf++wD9CfgHAPMCBPsGCPT++PcIAP8A+/7++AAN+/8E/v8H/v0C+fMB//n5+v7/CwD9+wYAAe8CB/4G+AUB/AP5BP4FDfAF//UJ9f78APIGB/wAAQgKAfkGAwj/AQAGA/8IAgD//f4A/wD8EPkLAwQIAAMF/gL9/AECBwIEAv0GA/wB9Pv/AwAB/fsGAAH2CAH//Ab89+n2Awv87Q/88AXt+e4K+wsE9AH88+/xAAoP/wj1BvoA/QcDAPL6CRLuAQUGDfAC7gb69Pn9AgAH/AQDDO8AAQEPDvkF/gXzCPgCAf8CBAADBvkA+/4O/fkDAPj2/P0J+hIA+vr9/fUJ//oKAvP9/AcM+/kB9fn0Affr8fcA+/f4AfsKBBH/C/sBEv8D/f4D+/sI+g70Cv3/Bvz+BA35/Qj7AQME/gj7Cf8I+v8JAAf4Af7/+wEBAvrx/AoG/wb3Bf4C/Pn/Agf7CwAD+vf/AgII9AQM/gT6AvgODP/+AvgAA/7//wb6AQUB/Pn+Dvz/BQb7/PgGEP76/f4A/vwCAgTtAAIQAPH5BgLx7gbw9QcJA/30/wL3A/sD8Q0DAAUFAPoDAwEC+REE/QEI+fcFAAAU+PwL+vf9BwsEAQkC+PoDEPv39wn+8QUHCwbw+wIQCP8MCfwF+gIA9wcKDwAH+P8CA/8H+PQQ/xIB9gD+EfwG8gP+Bf0H9xL4/fESBQX0BwQDBPj6Cg79BAgJ+/z5Bv4L+vL3+v/2CwUA+fwMAQT3/wcD/vf2/P31+gMH/gH8+wL99PwPBvnt9PYI+PsBBPj+8QT1AP0P/ff5Ag8BBv76Bv/4AQICAP0A9f37AgL99wv6AwL+/P0BAPwDDgD8+/UF+PoDAQgA+f8EAgv1+PUC"],
    ["drinking-water","safety","8gQMDu728fcH9Oj6/QT9Ev4CAgEH6f0BDPoH/wPx9/4GEP0I9fX69+gB//oBAQP7BPz6/AX7AQX9Awb/AAb8DAMJ+/cB+P79/AwDCPoD9AwJ+QQGBgv++gL7BQr2A/UL9Avx9QD/9wP29vsG+hD4Eff+/fL/CQAK+PL6BfoIAQsO9vz/8ggE/PwGBv8L/f3yCgIE+wD++ggBBAj/CAH+6AQOABYD8v/8BQT6BQH9+wAF/v0A/QP79vkBB/UGBfb6BAz7/v0ABf8E//f0+AkJBA4A9f38//sMBwEDAfr++AMA+PkKCPwGAfwECf/5+foB+Qz9/QQCBvMEBwoF+AoIAvn9/Afy+usTDPnt6wIB8A/xEQAEC/QF+wcK8vkBAQP9AwT4AfkEAfzn/wQC/BELAPz39QoB+fsP/P8ECP8L9v0BAf0NBgH3BQH8+g7/Dvj5BAIPEfT+BAYP9v4NAgvzEv309vj/AgAD+AUL/vwB+gMC+fwM/wIBD/cC+QgF9gDzBAzzEfQOA/b4/QECBf0E+woBAQH9Bv77/v0D/ggD/f76CgYM+vX+//f8/gH1Avv7/vrwAAIB+/oG+wn2CAX/+/4O9wsDBQj4Af378QgACQsG/wIJBPny+/8DAQcGAAMG/P/+/fn6/QwEAAMA9/39+f4KBe38/wkBBgkJA/4EAAAB+v8W8PTg+Aby6/ns/P8P8gQO9wL2+vgUBgkFBO/7/AYE9wPu+QP37fUE/w0EBfcK+PkECv77Cwn5CQT1APwF/Qj6EfoBAAr5BAf4/gb6Cgf/BgMC+wUJ/gYDDQL+8Ar7CPjyAvr8Cfb2+vb+DPgI9/kH/wMCCgb89gD78AL7BgH7/vj0C/0AC/4M/Av//vkF/gP+AAADAwIDBwACCPPvAQYJDfr7/wH6/gUAAQID9fsG+vf//vj29wQO9QkCAQYBBv/9/wf9BAX5+O/6CAADCPr8APr3+QcN/QwCA/kG/wIE/wX8+woF/QQFAv79+Pv8CPkDAgcLAAAFCQL7AAz4"],
    ["food-outage","safety","8A0EEP/0AAgLBPf2/fwCBAH2+vQCAQEEAvrwCgL5B/n9/gMP/xb4BQcFAQjwFO0D/vf5EwT1/Pf7CPoJ8/z7BAMAA/vx/gfv+wD89w31Bf/4APkN+ff9BQT9/gP7BgIH+Qfv9gPt/gAEAPn8/Az1Bv37AwP4EAgA/Pv7BvkJ+P4C/gYC+Q8F/vcAAPoD+wsMEP0A/PoC+gAGBvz1//0G8/kDDP8DAPUG/QP4+Pj0/voMBf8BBv4NAvsFBwIJ+QjzAfMC+/sA//j2AQX89wQP+Av/9RH4/f4DBgEG9/X8+wENAf8B//MBBe8JAQf+AfkH+fPz/w4LCgEBAwYG6/v+CgUHCRn0AO8QCQLy9fj9+BL1APnvDgP9CfX79g4C9AINAPUP6AQR//35AREACAr3DALzAvkNAgEC8f4HBf/8BwH99/339AX9/vv+7f4C7/0GAgj9/fsB9Az6AQUDBv78EAj+/f4D+wQLBez8Cvj6/PT++vARBPnv9QQABgn7/AHyAPsAAQQKC/j1EwIHBf/5/QQBCfn6Bgb/AAYB+AQGAgkOCQX8Bfr3BgAAAPsF8/n0/gr9/Aj+B/sK+gEAA/8B9gMABBAA/Qb6/fkD6//++P4G9wcJBgT2BAUAAQL4/P798w3+BQL+AP3+/AMD/v0BAwYD/v/8/Az8+wADB/v//vv2DBUR+P70CwH26/D/BQcI9/8C8wIJ8PX17fr99QMNCwwKDv4HFPoABAcD+vUH8Q/5/PAACPz//P8I8BIHBP39A/X49gP5+/v+/fP/DPUGFgMD/gAG9/oJ9/EC/QUDAAsEAgAA+AsCBwPzCgkSBAb5B/39DAQOA/sN9fwR7/8D/gcA+gMFCwIM+wP1APoJ9wT8+P3xBgcAAQIBAPUE+AAB/AL4BAr//PoD/fD4CPkB+Qb+AfsFAgf2AQ0F9QD9+/cC/QYH8v8D+Pr+BAoDCQH6A+77BPkA/AMM+fwA9v33AAIG/gj7/PgA/P7/Afz7AAH8Awj4AQEG+vH/AwkBAfoD"],
    ["sanitation","safety","9gALEfr1/Qz09Pn4+vj9C+789RIA5w39+Aj7BwH6AQkHEwMDCwIL/v0F+fMH+g8DEwMABPcBCwj4D/sABQD6CwUE9QIRBgUB+PgO+PwNAPn0+QkJCfYABPkR/AL5BPX0/PwJ+wQGAP0DBAr28gv4AvcB+P78A/UP7gP8DvcI+wH6+v366v4FBPgACP0J7voBCAD5//0D9gAHBQgD+QcH+vcHCv0B7/QL/vL7BwAH/fv68fP4/AX2/Pn+B/f6AgMABv33+wEJCQX4AQICBPz9+AP89wD+BfzwAAAI/wIHA/4CA/35BAH+BvwDBAr/+fj2BAMF+v4ECQUGBfsB+wn6DvkPEg/+9Pj+C/Dt8wn5/A/6AP8MCAgKAvb7BgsH9/sKAw0ICP4FAO4BBQL0/Abx+vkIBgkC/wMJ//j3/fAC4gIUE/z1Cv/7B/kF/wYI9ggJ/PH2Afv9AAQD/gL/Af/9BgAE9fX87AL19gIICwkK+gAHDv73/wEEAP3q7gf8+QUBAQT7/Pj/A/jz//4CA/kDAgICBQX5/vwB8QYE9gAC+O3/BAgGCP4H+gcF/AkAAQkVA/n1AfcBAgX5CAr0+QP8BvcL+QQACf33/vr3+vgE+gP9APgD+fb+AAMDAfvyAfYG/PsABgvyAQH4Bf/8AvQGBfwEAfr/+Qr6CAAI+/79AAT7BBELAe33/PP4+OP1/PkQ/xAAEAn8FQT67wcIAAn6/wQWAAwHEP0IBAMH9wkJA/UHCgAL+gD/AO8M9f0BAvECBwX/+A4B/O8BBQACAAIAAvL3Awj7AQP/AQgACPUK/AD8AwYM/f4G+fj5BQ/4C/n+AwD2AvgC+hH//fb8+QoM+/f79gT7/QH4/wMKA/gAAwAID/0GAgT5BgABCPcG/P/9Aw0DCfnz+fb+//cBCPwJAwD18foC/f4A+wIE+O8G+QD69Pz5/gAR9Pn78f8I+/0C/wP5CP79+vkDCAD4AQz3/AAGBvYF+gb//PgC+v/7A/f9/xT59wEH+AQIB/v6CPsN"],
    ["febrile-seizure","health","6/b2Dvv0DBT+CvcE8gMA+vQIAAL6/wPs/v8KG+8B+/sR9g/3BP3wBfb8/P389v359QvxDe8A+wkK+vsKCAn97gr8CfcD+gby+v0FCgQF/fIK9AX6Av0R7wH9Bv4M8Pv89Qr8A/v99wsEA/sG/vsFAvgFB/H2Af0DA/AB/QL79gIH/gkF/f0LCgAQAv8K+/z9/PgGAfL7///0+gECAQb1+fkBCf8IAAv/+fj1+/kM+fAFA/8D+wIDCf0BBAEG/gMO/wIQAP8E/f//+wH+BAH99gABCfv+BQMJAg8H+gQJAfoAA/8C+/4CBfkEA/kG/gQC/v4GBgYCDPsICwEF/vXw+ffu/wvz/QD9/fP6/gL2BfYMBwH96g79+f7xCQQF//4JDPrz9//xCwr9AQb++gbyB/b9/Qr78woD7wX9+Q/79AEDDvkA/PT/Bw4P8wj7Df79C/sF/wYQEAAC+/cEBPoE+P8JDP/2C+0N+Pz+9Aj2B/j9AgIODwUA+Ab67AkNAv4AAP//9P7+ARH/AQAF/fv7Cfn6AwgGAv77+P8A/AAG8wP2/v0AA/4MB/v/9/v09vEE+AEDCfwK///vBgH8Avz4CAD5AvwMCQ4F/wAABQv9AwcL/RPzBAYF/AkGAvwMCQL+Af0DC/oI9AH/AwX/BAIDA/v+AwL//Pf2+fn5+vf77v3S9/oK/fgGAf4A6wP0+hH58QH4AfT+9/EH8gQQ7gf+ARIFDwH/9PkF8gQG/Qn3CgLzD/8H+wL7Avv4+ATkCgf2+wH+A/7z9+8BCQIBDvj7/AP6CvgB/AkA9vr89f/v+gH6BPX8DPYACfr2//P6/vgKAgb7CPr5+fsC9AUQCAL+BAH/BPsFAgoG/wUD/gL2+QoH/wP6/foLAPP4AwME+P33+AH/+wP9BvsE+fPz+QL+APwFAQT6CQj+A/8ICAsAAgj5/wX5AQH+/vwGCf4FAgQI/wAICAQIAwMFAAL7AQL1Av8I/gT/A/j6Bf4C+vgE+/gB/v0EAAkA/wUCA/D69wL3"],
    ["cold-water-injury","health","8v/2Cfn4/e768e0D8QL17e//DfYI8QEM/fj7CPz5/P8LAwjx9/QW+vsG+foGAAgBDvEG8v0CAggPEQkQCPwRBfMFBwQH+fb88PsM+wf3/QLq9gH29AP9AAcS/goN/QH6+AbzAwsB8gv79RUF+wj5CPX1AQME+f8B//kC9QADA/8GBgX4DAkU9PsLBgAIBPb9/gUB/vwG+wIGBgD/EAH0+goBAQAA/gUFDgQGAQH4BvYAAff9AwD7+/kGBgMEBgUFBPsD+/73AwkCCAkFB/z/+AIA/QgDA/8BBAMH+gcEAP3/CvkAAgH9B/39/gIC+wL/CP358QcJA/78A/wD/AEH9+T3AQr78vIC7fb5DPcT9gfuEg4F//oK8wz3AwPy6fUCAg0J9PACDf31/Pj7AQQBA/PxAv8E+gT0CwX89ff8+v/4+AMJ+uf+/v3pCgj69/j9/xP3/gb9+v8FCwIEAAT79vULAPv4DvoI8/gB/PwDBAsHBPj7B/L5+fb6Bg/9AusFCAMJ+PUNA/wBCQL+AQgD+/3+/gX8BvwB/QEB/xEH+AMECf4F/fQKAQH7AggIAwD6+wEB/wb79/3//hT5BgYAA//7/P7/+QYBBQgDBQEK/v8MAQn+BgIP/gj7+/n/BQL5AQYB/wH+BPv4+QAGAf4BAvwJAP4CAAQHAvv5+v4DAvj79/oH8Pj/6/L3Avr2Avnt+BMJ/v32BgID9wIIA/MCBAzyBPb5+wjx9//6AQH9AQ309gD1//0F/hkG/AoFAQX5//0P6QT5/QP7/BX5Af36AvX/+PL3AgD+/Av8BgUB/v0J+vcKDfj5DPr8EwYK/v0JCAIN7w8CDPkA+P3zA/8C/wgFCf0LB/j87wr7+vz7APr4/P7/BQH////+DQgKAukACQUF/Ab8CQkMCAkCA/sK+/H99/z2/QAB/QQL+wQL+gkE/AL++AEEAQIR+wQL+vf7BAQLBQsFAP8DBAr1//j/AfcP+gD9+wD9+fgF/gX1//4ACP/2CwUC9wT3AAMGBQH+"],
    ["ice-breakthrough","health","6v0ECQf6/fz/+PkH+QEHDPsDGPT/AP4B/u8D8//uAA8ADP7tAPwTBfr1Afn/DBUFDPj9+Qrz/gwJBvz3+vP5BQECBgT/9gT//AQA+fv3+BH8/gD87AgB8wgBB/0QA/sEARb1BgEACQTx//8GAfgEAfz/+/3/8vj7BPX6//72+fcGAAH8AwcL9fkA/Q4CBv39//j7BQD+Aw0KCAj99gr5BAT/BA768QoGAQT9B//88fcAA/n89//5/gn/EPQJ+v8AAf/89P4A/v8HAQYB+/8C+xYIBgQV+gADDvz9+vUHAvf/BgsB/QMBDPn8CwgD/P37/g32BgL/BQQI7gL+/Pr+Avf7/xP//fX3BgLzA/AB/Q//ChPn/RL5/fvuC/8B8/wMDPoW7fb9Bv78/wMDAQX1CPr8BPUG8/8DBAQG/P/7A/n1BAUNAfgA9/T8+v/78gIR+/8CA/v5AA38AgP6Ev/9AAQL+vIR/QED+/X/DA8BBQT9+wL9CvQJ7wj3DRD9+fT2BAEE+QITCvz8Cf4ECgn1+/8B/wP8CAoAA/wN+QsD9gQMAw0GAQH+Bfz9+PwI+v/3/AX6AP4GBAABBxALAAcEBgD3A//+BwEGAQb6/Pj/+fcD/wYABf8CBgj9/v7xBfcC8wYB+wj9CP4ABQMCAQMK+wMM+v0H9A4J+PII/wz9+/npAgAR/f728v38+fnx/gID8/sa9gcH9wYH9AP5++0EBwIRD+YG/A/98vwE8/sJAwEE9vf7Afr4Bg0I/wj39gj9APsFDAH3/Qb3Af33/Oj6E/oJBgH8AgEG9wP7ARL3//kGEPADAQIFBPEC8gX6AgMK/vryCwX4AfH/+QMCAf35AQUJ+P0BDwv5/wP8AQUK+PYBA/oB/QYFBwwGBfYCAQAEEgUICv35B/4CAQgJ//j+7QL//QQGA/z+BPsVBwcA+wEC/f/3AAMBDQECCPn/B/b7Ef8L/AL8/AUK/fv/CAL5/foJBQD6AwYF+P4GAAP/B/0ABP7+B/8GBAHzAP8EAw0B"],
    ["immersion-foot","health","5vr7Cf30AgHv9vANBv8A8wUC/vv+9fsJBfbtDQkC9wQa/BD0Av0M8QX/+vT9/A8C/vb8Ag8A+wIPCgUKAQEKCvL9BfcU8/8A/P4E6wD18AXt9PLx9P398QIL8/3xAfv5+wABBAj++wb+9wYKDBEFCfDzCPb8//f2/wH/7ggKCv78CwH6CQAM+wEDAgb+/wP/Agb9CfkD9/4ECQgBEP38/vv///kL/fj+BAj//wQACPsC+fb/Av4B//0G+v0LBQIB+vsAAf/9CgoEBQcBAgL8/v0BAwf/AwIC+wcD9AwBBQYCBvb3AP4CBPz6BQX7+gcEAvby8/wAB/76BQEABAAB/fL/+hDq9Pr89v3rBPMDBfv+CPECAAIG9/f8DA4K+PgRCAIW/gn3CAAD9vfzBvr+AAb0+wYK/wD0FPn7DvvzC/kM9vvyCvEG+/z/+gYDAAMB+gYICf4J/vf9BAj2BAD3BwH5AQYBBvUE/PEPAQz+CAjzA/0BCAD38P/2AwEA+AUDCgQH+gcABfz8BP78BfwB8AH3+gT9BAAF9wEK/wT+/QUQ9Pj/Cf//EQX5Av4I/AT89vjw+PYD+fv/Ef/5CAEBBAPzEwT5/Af++REAAgD8/vUBAQMN+gb+/AMOCPv8AP8C+AP4AAYACP30/AkK/vD8CwAC+foFBgr3/P8EBgUJ/PXn6gAL5/D6A/Pv+QMB/AvqBQf6B/0BCA7+7PYDAfcDDBD9DwH9+gHz/vf6BwP6DPD8/PQN+AP5/BgF/wcEA/v++vsECBL5BPTyBvT2+vj1/vr/BgEJDQbsARD5//YF+/75/Pb9Af/5/gH+FPQJ9/kMAP4D/gsGAf0D9fn6CwgE/AYE+vkDBf8F+AQE+gwCEgcD9QT++fz6+gEEAQYDAvn5A/f1AgT2/gMBAv/7A/gA+Pn49Pj0BgH3/QIE9Av9/wz6+wQEAvX8CgYK/QQD/PoG/AsBAwMIBwMICQoCB/z7Cf/+AwQG+vsE/QILAwP/+w4BAgr6AP8BAP79/wQFAwD/"],
    ["fall-from-height","health","9gQPDQn8BPPvCQIQCfIF9AT7+w8PBPYP7fMA8f/79f70Bv/1AgwH/AYDBfcF/ggD9ggFBfP/+wUEAfEL9BXqABEI+vz5+wT7/gEH/fjr+wnr9wz2Avr+9fz7DvgIBfsLBvvx/AEDA+wHD/0GCvf9+/j8BO4L8f797vr+Bwb2Afr8+AUDBP8G/v39Cwb5AAQC+gMF/vwDA/7/+gT6+wUAAgwF9gv+AAMACgT8+//v/wQK+PkR9QEI/fz7CgH6//r+/f4DAQX+CAD/Av0K9AED/gT/AP8D+APw8/37Afb+AQQH/P77/f4JBPP9A/4EAgT3+f8HDAn2+PwCAwEEAQD/B+0DBA0LB+708wX2DwX7/vwP/w0FB/j+B/cB//r3+/wAAAoDBQX7+v4LAREA+Aj/7wb6/QsRBP0EEvv/B+8MAwAQ5wED9vUGDfUOAf/++AgG9gwP8/b1+fn8AQEB9/8G/vsD8wD/AQDq+Q4ACQ/rCAUD/wbuAPb/+/r++fQAAQP+/A0CBQUEB/H7BQ8E+gX8+AD6BAn7/gb7A/sI/gAK+gP6/vsKBQIUAQL59gX7Af0A+fT+EAgBAv76AQgD/Qj5CP0EEQD8AQgMCAMDFAQHCf8D/fgGBPYI+/4G/vwAA/8C/QcA/QoCAP/v+P8D/fr8/P0ABgX9A/r//PIHBvoBAvvlCAkIAO7+8+z88wP9+/0F/QkL/fAB/AD/+wsMAP0LC/sLAe4I+P73B/cA9AIA+gAF+wMEDvkDBQ7t9wn6A/YHFfUSDvH1+v4NEvoF+vcF+Qr68/wD+v8J/QIC8gQOAf0O+v35AwQF9AIG/wYCCwL9+woBBgL9/AIA8fH7BvoC+gLyCPoG/wMACAT1AP4JAP0DAPz+/AX3BQD6+wICBAcC+AH+AQT7BwD+CfULAvrzDv77/gj/AgP9/AcJ//wI/wj08AAB/P/0/vsO+vn0A/wI/Pn+BAAE+QQI9vP2+PwE/PUAAQgA/wr//fX2Bgz6//kA/gL/+u32+/nyAA73+goA"],
    ["flood-mold","safety","6OwCCu309gb9CP3z8f8FDv4GBQIK9vEE/PwRAPEMBP0aAgkGAvsTBf0H+PbxCADjB/f4A/fzAfz+BQEOARAEDP0G/fH9Chvx7PwL+/gABP75AP0J/P4MAgIO/QH+/wIHBwf/APsECwj98Af1/f0JAg3+/An+CAv+CgH69gb//AkF/wf36/0H/wv//v79BAAJ9wQB/vj9/QMD/gH9EgP3AQb89wEDAAz+9gr69gsEAPb//wf9Af77/v0B/gUF/QAIB//9+AEHAgv+BQEEAwkH9wv+/AQA+gX3AAUB/gD+BAX+/v8H/v8DCPgABAQC/vYB/Ar2/gj9+/4AB/oF9wMKB/f6BQnu7/Xt/wbt+QQMAwQVDQMIFP/27P/3//0ADvQNAAgMEQfy/v38/gD+//8P7v8J9QUNEf3/BAv39Pb8BgwFAPnsEf0MBAMF/wLy+fP6AgH+BfoN/AAH+QH96P70C/8OAvzv//X2/O76CQIEBAX0Bvb69Qb4+PAB9/4F/PoJDvwA/Af+AgL6DAP7BAEG/QEJ+Ab4+/sJAv37/gAD/foQ//r//gACBff++f/0+wX4+/f89AIGAQAD/gcJBQUECAz6CPv5+gMFAgv7+vwE+AARAgYF+wH8//QAA//9/f38C/v6AAADBP8D/wMJ/fwEBvkEBAIB/f8CAgUFAfgICv4D9gIV8u74+vr37/QAAgv2CPsFBw/9/wX99/Tw9QrqAQ3//ggKCf3z9PYOAvbsD+/2/vkOBAwP/ggN7/P+BQYI9fQB+Qn6CAL/9gX07+/7C/z1Exb2Afr2BQII+/L6Av3+Av39+gj8AP/5+v/7BfkQ+Pj78gYEAgcA+fz9/fv7DQUCC/oBABkA/v4DA/oG/e4A/fgC+AL8AxAA+/4BA/37Cfr9A/4CBQQD8vkM9QUO/QHz+f4CBAIB/P7+AAgCBA4E+QL3A/v/AAEB/f4FAv0CCP8H9wf4AAEF/QP6AQH8/gMG/fkAA/wGAfkCB/v8/AEFBQMAAAD+AfoE//38/wwF"],
    ["flood-evacuation","safety","7QIS/A/7+PUC8//2+v/8B/sE9f4L+Pb8+QcL9/8GCgYG/vcJ/Qf79vz1DPP99gH6/QX//wwE7v/8//4H9xcUBQIAB/f79w/5Av8L/foM9fgCCwoD/AkO9QoPCgv6EfsO/QsE9/j7+QAABAX3DfoECf8L/gH9Bv3+BRH2Bg8D8/YC8QD+A/r99wMD/gD7+QUCBQL///8F+fz0/wD+DgT87AoC+f76C/kBAfz/A/0A/vz89f8C9vr8BwXxCQEDBfoJBw4C//H7+AUGBQUIEPr8Bv/u/wgA/f8ACAAGEAL19/oB+f8D+PwDBgP69gb4Cvn2/Qb77wUKBv79+f/59gT98f4ABwH3B+/3+PgADQP87vz3Af8CCPn+DfkFBvX98vwB8xT3/Ar8//8BBAv0AP39//3//QD5+/QP/gL3DfsH7goEAAQC/wEG9/YGDAz6BvoK9AoW7/0ODP0HBPwMDQDsEPr88AADAwLr9vcHAwUAAxD2//3v9wAFBvf7/gMR+P8EAg8A/fgIAvAA/wcM/gT++/30Cwr+/P769/z49wT9DPz+CQkFBfn89fr+AQIEAQMBCvXz///8+foAAQX1DwYKBQAM/wT5AgP/Af8A+wcIAAADBv8JBfP/AQsH+gz/Afn/+v0AAQj6BQX6APn/BAD37AEN+/UA+vj2BQ0C/QgNCPf3BRYSBPD27fr74PL4AvsIAQX+BAgB+vcBBgsA8wDvBgEI/v////r9/v389fT8Bv8JAAAOAvj5DfT5+f//Df0LBwcE6QPxCAr9De0A+f76/wb//gAL///6/wH4Ce8JCgv4Cvb4/Pby+gQG/P0D/xMMAgf++voFCAn4//YL+gcD/gb9AAgCAAb0CA79AgD8/v0ECQP6+w71BfMNBfQD/AHuBwQEBgABAAYGA/UKAPwJAwMA+ff9/QT7AgUN/QEM+gMAEfUF+vz3+gL+/fYOAgf8EPv7CP/4+wMA/wL7BQP0BAMAAv0I9gb+AP8BBfX7APsGEAvx9v8CAQMHA/n3AwcE"],
    ["urinary-retention","health","/PL1CwLqAwLtAPLw8gn5+AIAAfj+/QX8+P0OBwL+DhAF/vMP+PIGBAD9A/oR8wP1CAIG+PYF8gIACvX/CwMC/AP+AgUEBPkABxIK8AcQ+fX7/gEG9/j5Av4D/vjoAQD5/wf6BvT3/w78CAMHAgYADPb6BAnvEvoE/gsJAAAD/ggA/wT9CvsR9P8ACgsL+/4K/AT7DP0JBwH//hL4DgbyBAXxBPH3+fsD+PUH/fUFBAD8AAEH//36+fIEAwAF+vz3+/UB/fUADgUHCQcEB/7/Afb7Bwb9Cwj9CAIG+wgC/QD7+wH99/n+AQD9AQf49wEE/+73A/n5CPsHCP4HBwAEAg0I/gMH9vgP/ffu8/AB+Ab5BPfzA/395wDr+A729wz9BAINAfgCGRIEAPDyHAb7BAz6//78BvX9C/wEDAH4Dfz6+AH1AQ4DBAQFAvfwDgUK9P/4FwL29w37/fYBAQkF8AQAAQT+AQoBDQMIDPYP+Qjq+f8HAgb1CP35AgcDAfn//gb+7voABvsH+AEH/QMD+wED8/wEAPwGAgQB/gf+B/f9BPz0CPr//P35+/4IBgMI/wABBf39+v37CPv29P38+Pz7Cf4D8wj7/P0J/gYKCP0B9P8B/gj/+PwABAAK+voABgEH/QEBAv0A+QUABfz9/gz69gb++QsD+QQH/fz2AgTsA/IR+uX8CvLv++71AvwA+fsA/Pr3AwHz/AgD9vYM/wX+AP3+7AsFAv4H9wL1//8M/BMMC/n8AAwB/wQL9w71FQMI+wX1AA4QDQL3/g0FD///CPsCBQT/BAf+/u4I//r+9fv9CAD/+/YCAgcKB/sV9gMNBvQKCAb1Dwf9CgUOAwAAAQABBgv//vUEAP3z+/n+B/YF9v7+CPwEAP//Bv4F/wIU/wv7AAL+CAcLBP///wj7+fsABvoA+gn3+Ab9Bvr8/QT5AvYF/wL//wn+BgL//fn//wINCAT9+vz1AAj2Bf8KAwMJ/wAL/QYBFQcCAgAF9/v3AQPt/Pn/Cv4CD/UB"],
    ["testicular-torsion","health","3gTxAv7hDfrwCPf5AwL/DQcG///tAQ/19gwMCQH5+BUOA/0A+/b7/AcE/RYG9voEBwcE/vwK8vsGAP/2CAL+/v76Bw74AvkICwQJEwbz/AQA8vv2AAD3AAsCB+n9Cwf2DAjy+wP4+Qbx+AsIAAb4BP0ACATyAQf9CQgC9f3+Af0FCv4MDfj49gMI/f8JCfz99f/0BwgB9/MAAAMDAwj1/fkCBwYE+v8CAgsABwQF9f///QP1+gf8+gP6BAIC+gP5BfYEBwD8/fz7CQEABAIH+P8F/Qr1CfcFAff8/wII+woBCQD7BwgA/gD5AQsHAvT9/f4GAvz//QsI/v8JAQIE+ezz9Ab6/g0B+QMBDfoA+PkACPz49vAD9f4DDQMC/gEJ+ggHBw7vAAMU/f8KBf3z/w0C/g7zC/cICwQDBQUD+PkE/f75AgL+/AkI+AQH+AH8+f/2+vYMC/sDDQDv8gwFAAL78v/0/P8F+PYEDPgA9g/+CRn+BAv8DPX/CfwBBfj3CP76Bvn59AYDBwj4+QD9Avb5/gQB/wr7/fb8+vj59/wGBgYFBvj8/fgL+gL+//rrFAYK/QD3/v8E/RAD/wASCv3xCPn//vsF9QT4Av73Afr2AwkTBQT9BQUBCwP99/cG8wL59wH89wAD7v/8/gr89vUE+//7/vgB9AoG/wYD+P/9+voH+/D++PMO+QkWCwMJA/j7/QADAwAIEQUQ/e0J/Q/vBPz++AT7AQcCAwru/vwWCP8C/gD7/BAT9+8CBg8E+f0GBP0IAPIFAQUGDP/98/f2/gX8BvkDC/f29vv9CfIIB/IF9wTrCPz2A/8EAAEB8gD99/oG/QQDEQf7AfEUEv75B/0G/AfwA/v/AgX37/sGBvf/BwT5+PsKCwb/AfkC9wIF//v5/RUF/voDAATyAgQMCwIIBwMFCAkCBfvz9P8NAAUAAAQHB/4H8wYA///8AfcRAQABAwYH/wT6AgL8CPkFAPcF+f4G+vsFCAP2Af/8+Qj8AAT6AfsCBAn8Bf4B"],
    ["diabetic-ketoacidosis","health","8ebl/vL1AwwJ9egAAwXxAP8IDPoS/PYEAxAEAvfw7O0B7PsIDQoPCgkO+PX4DPz9Bf8A9wcJ/AAKAhP7/Qn3AO/+CP0JBQUC9vT59wUE9f4A+/4J/Qv/+P8FAAAE+wYB/QP4Cwn/DvPx9QgG+gYOAAYI8gL//wP8AAQAAwsG/gMC9vv//wn4BvAA//n/CgcJ/QoBDAcB8gYD/PgH9gIHAwn+Bfn+/gQE/wYD/gEN+PcD/P38+/4M/vj6Awj69/77BfoD9fv3/wT//wMDA/QE+wACBwf5+wL1+P8D//YCAgD8AvwDBP/8CAD/Bwj3BAf9AwD0Cgj///8EAvQD+wMGB+/37vv68f4MA/Do/wEW7wD5Av79CgT6AAYT/gP2+QD1A/Tx/AADFQX8EPT28g3/AwDzBf0EDP0D//oO+/0UAQP0AgEBCAP/Bfrw//oABvD3+P8BB/4IAgAB/f8DB/AO/gAC7voR+vvu+OwLBvT6DwL5Afv5+AIH8gf8AQMF+gQFAgT0+wP7+gbv/gH5BhH++gICAwoEBvYA/ff/AQECAAL+Bw8IBAID/gEA+AEBC/77BPL7AgUK/vf38QEO6/H+/AQCBvn+/gQDBgcCAv/4CQMCDQkF/gAEAf0D/wL8AAAFBgj7AwwE9vv/AwIK/f0A/AQDAg3+/AAEBvv5CP0FCQToBvILA/EFDgT87QnuFgMB/v4B7AIT//URBwr88fn7+QP+//jx+Av+7wv7CwoP/wAE//b2/g38CAD3/gHu/w0C/gT/AAr3+AUB+/Ty9gD4BQYDCfsAGPMCBAL4Avr0EAYDA/T+Av8I/PrvAQH9/AYOBPv89fEAA/j8+P7+AAX3/gAB/QQBA/8E/wj7CvgHCf79Cf8P9gT5+gX1AQgSAwoE/gMCB/sFCwP9/v8DCA0D+fsFAAILAv/1+O0HB/gA/QABA/73/P8LBQ/+BwEG9gD/CQQE//wAAQH7BAIA/Qfx+QIHCPoNBgABB/n2AAT89Pz9BfoFBAUG/Qf8APn7/A37"],
    ["sepsis","health","6AT5BvXnBPn87e8A7hP1+vUH+P8ACP4DEgcFAe/6APgN9xIGA/8BBvIFBf/9BgEDAfz/BgoKCAD2/gEHAgUB//UFBQAD/vnz8gDwBg7y6gH8/PsCAhL8/QPyBwAT6Pj4A/3zBP4BB/vv7QwJ/fr4//sC/v/xBP31AQ0JBfr7AAj5AAb+Avv+B/sH+/sUAvP+9A76BQIJ+wL48voD/QEB/gT+CAcA/AP2BwLvAAEK9/T9AP4AAvkD+f38BfwD9wQFBAj99AkCAAMAAwQDAvsFAwkCDgsFCf7/+/sBC//7+vkACvgD+wT6BAQB/QMAAf73APgFBPv8AgcD+v0IBgQACewAAAr12QsR+/H29O8MDAQEAvX5+wsD9wHzCv/88gYEDfcSBP8MBw4B9wEJCgPv+fkK+f4D9Av7DAb4Avz/+gEF/wP+BfIG7fX9Cfr79wQIAPsLBAb9APQH/Qb3CAT+9AD/AAv/CPwC9PUO//sNBAj/AwQL/Pz9+wL6CP7zBQcD/woC+AEGBv74BPcHBgQD+/EI9Qz7CgMC8vsF/hEB+P4G8wX8AQUH+/r79vUGAQT4Av35/gIDBP/8BAXxAQH8CgD/BAby//r9/QD5B/4H9v/9+QAJAwn9AAQNAgH5/Qf+BvsC+wUJ/wwBAPoA9wXyAP30/f8L/wMBBvcB8woO+wEE/QcH8ukI9f/w8AEFGQzxAQEA+/TvC/kPCgH/9foKBALtCvoW/vsBA/X5ARABAfju+w3zDgT7+f/3+AT9DOwG9vcHA//7Dfr48QUB/vrq8P8G9Pbv/v8FBPkE9Q38/wD9Cfz+AQf3/P//C/zy/PX5APsSAPkB+gQECwj78fsBBfz0BAH8Av8E/wD+/g0G8ff1DPP6/wf+/v79Avr4CQICAwIF/QH++foI/Pr+AAj9/QgFBP7+CAf7BPcUAwP3/wYHDAECBQD6/gYKBQQHBAABBAIKBQD29/4A/wEAAvn//gYH+gIAA/v/CgAFBAAD9AEK+gL8BAEKCPv7CP0KBvf7"],
    ["hemoptysis","health","AfQAAPHf/gsHBQgBChr8AP8I+QoABPoGA/gP/gLo7QMHAwwJAfz2DwQA7vEG8vn98AMC9PcMBvMDB/f99wYFEPcA+P/+A/n7AvwB/PoMBPrz/wIQ/Az47A0DDPwQBfP8CRDsCwP8BAD6+wD3/QQP+/8M/AT4BAwLCwECBPII/fgU/Qb8/AH1/voF/QL0BfkD/f//BwUC/gb5/AEKBQEF/Qrz/gECDPH/Afb5B/4IAAP7/QYCBQYHAfT7AgIBAQkCB/8J+fz6BQAFAQr5AwcABf0C/gUKBv/1AwIDAv8I/wj++AD7BPf6+AH09Qn/BwX+AP7/CfwCAgAFBfr//gIA/vL5AgXx2v4J+wX/BwQO//MKA/UNBP0HAQH1DQoK7+wCCwIEDgH8AAb28/UBAPn8Avjr9vQD+Qv4ARD3CgUAAP3oFP8DBgEACgAG/wPxDfr79gz8CQUV/+8G9/j+BfwB+A0L+fn+/ALz/fcCA//4/QP6EfsCAwAZAgL3/Af4A/T6AwT2/PIG+ff2Dv38+QwDBfUC/hICBPz2+v79/wQJCAcD+wH9BQXz/QUA/f/7BgEI/AEB/wT9DPj3BwAA+/kGCAMDBAH8AAgAAwkD9wIAAA0ICQYEAf4I/AICBv74BgUA+/sAA/4D9wEBAfwGBf0CAf4B9AUCA/3/Bfr2AfoJBP7xBPkK8uQCBgUF+wMGCPX6/gsCBw7/DQUO/xMGC+/eA/vr+wUP/Qj4/P398gbxDAf/AAYG/AMD//8S9gPyCQoC6/b5AAIVCQTuAvn4+wjyDfH7+gcAA/rz+wL6+P8P9f3+CfYI+Qz58fn4AwD29v0GBwUFDPf3CQwDAPoF+QgA/AAMA/wEDQIA+w//APIGA/77/QMBAvoFAwX8+/4F+gL7CgX9B/8G9QX++fsC8wcDAf77BP4FAQED/QIDBQf0AvwF/P/+/PX7B//9AvYABgEQ/vYKAwEDB/cEAf0B+v7/BgYC+vwBAv0AAAP+AvwK+v0DBPsCBP0CEf0K9wYAAQf/"],
    ["compartment-syndrome","health","9/jvAwL1Dez3+P4P+AP/3wcK/vb/+gUE9Qv0DPf9/vcK/Qr7+PUJ8xIL+QX1AwwBBOoL8QMICQUYEPwF+gMQBPABCvkF/PUE9PkW9AT1+/ry+PP29P7xBgUN/P0B/wD9+gX4AQ8E/wn3BBoG+wfyAPnyAQL+/v78/wb8+QMFDQUKCv/7DPgL+AQGAP0AAwEABgX4/AD+AwMFBQQICgr4/wX5BfgF//gDAgsC+P/+A/4JAvf8AwAA/wIA+gMC/wH5AfwC/QL6CAIHBwAJCfv5APr6BQYAA/38Af4C+AAEAAf6/vnzBP3+Af748gQCAQX+/Pn19AUC/f/5BgAB/AQBAPH+AQoE8g7/6wkACP/tAQIH+RH55Af/BPX7+xP18v8EAv/59gv49fwAAfsEDAoIAQUCEPYD/fT4AAPt9vz2Av8B+v3tBgXtB/8K/QEF+QkA//z8//sF+QIE/QvvEPoD/v8C+Q4JBP4R9fQPDvgFAg74/Qb2/wD9AwwLBAQGBwzvCAQIAw4C9f33Avj9DQgDB/YE+QAH+QX3+QYJCAD8Af0C/AcBBgYBAvkDAAUC9fr5/wn9/gMN+/YHCPoC/AQJCPj9/Pz1+AL8/Qr7/wsBAQMFBAkJ+vz4BAbyAvb3CfwD/wELB/wJ+/r/BAYRBgX5/vj09wAGBwAEAfj3BQr//fzuBO4KAPEB+Or++gkA/vvm/ggS9fcD/AT49+4IBfQE+wUDDgD6+/nvDPvu/gL4ARD38wbwDv0BBgkN///6/QQP+PYO+QAC9/T5AwME+vLv9PT/9vL5+PX9BgP/7/IDCvkCDPgH/wz6C/4EAA4B//gI/u8C9AMJ/PP0CPUF+f/3+wAE+QYFCAf7AwD0DQUC/Pb/CAX/+AMG/fsBCP8WBP8A//sDAQQE/wAEBwf++wD9AwEC+vwHAQEKBgIGAgcI/Qn+Af75BfwK9wcSAgH++/8FAgUL+f8D/QP++wT2BAT8/AMN+gQH/P/5AP3vCfz6/PcC8/71BAEG/QL///kABgcA"],
    ["croup","health","9QEFA+/qBw7r8QH7+hP99fQF9w0OBuv4BPIKFPIG8vP+FQQLAPcD/hAPAvzy+/0G9v0E//MFBvsC+fL68wcMD/b7/P7/9fj6Avv4+QYG7PcFDQ797xT//Pr2Ag4G9QD/CA38+gjvBvwB8wkBBPYBAfQCAPz2CAQFCgH+AwEIBAcE/wj/+gX2AvwBAQD8BP0D9vsEDP7w/fb4+P0K/wsA/PcCCfv+DAAD/f/4APwGAO39AfoDBv8DBvj4/wD8/Q0CAwEC+gECB/oCAwL/+fwA/wQHBfsFBwIDAPn6/v0FAf74/QcDDQP1A/8A+Pz/BAMAAgIAAfAGAf8BAfT5/gP//fP+9/7z+AsR+vL/A/8S9vcCAfv+CgPs4f3kCQzw//YE/hMAEQEKAwQHAQT68vQDA/7/8Af2A/zyBwP+8//6ChXz/vsC+vH89BHx//oBAu349wsGCvwJ+e0K+QIDAvr5AQ3++P4M+f4H/f4L7wn4AATyC/4H/gAIBgf8DQH5B/31BP/9AAD9+QH0B/7+9Aj8Bfn7AP/++wH79f4BAfwB/QT/CQD/AAL9+vn//P73BQH1AfECCfkEAwf6A/oCAPoJAQb2CPoC9Qf5+A3++vn+//f9+Q8CCg8JAwYA/fj/AgAE/QgFAgEAAAj//QD9/QAD/wH8+QMACQT4AP34A/gD///h/v4G/+8BCfT0+fkBCAHy7P36/ggK7/f47wgJ6wbx9QYIDgb/CwESCwH9+gTp9QTuAfMM+wIH+/4E/gH2Bgz68gAKAwP2+vcP+/z8/Pvr+wQKBAj/DQnzAgAQAQj5Av0HAeoE+/MA+P39Af4E+wMEAwoAAu0DAgIJ/gUNAwADCf///QT7D/gIBAb+BAUGAwj48wQH/Pv+/vf7BQb9BwL+/QEH+QL9BvkA9fT4+A387QIB/wP9Bv0B//36CAP4Awj2/xL7BQIBDPkABf/3+gH//QIF+wEG/QEH/vz7+RH+BPr+DAEGAvj1AQX7BAkGAgT+CAIM+fr/AAQF+P7+/wD/"],
    ["retinal-detachment","health","A/sCCe79D+gF7AMABhEh8xT5AfsHAf4MAvcL9QT+/QoI8vz2//kT+wD6AAEC9QgB7QsA+gEB/AUE+AwWCAMICe4LAfz1BggA8AwBBv398+3+BQP1Av/5A//69/j1Ef3xDAUK9/MH+AL/CwX29er+FQIJAv/6/AcA+P38/gMGBPT3AAP/AvgDCA3/BwL6B/kG+/wABvwEAP4FB/8E/Pr5AAX6A/8JAf8EA/76BQACBfwC/wwS+v4E+wL+AQADCQf//gAF/Qr1AwEH/fz3AwQJAfv+B/z/+wMF+/4BBgP6Bv4DBQQI8AMB/QH+BQb/BAQHAQr5AAEAAQML/AQO/vz1CAP8+/sE9gPe9fYM+gICCvUA9v8C7/z+Afv9BhEGAAMH/Pn+BAsBBgoJ/vAHAvHp7/r+AQcR/QP5CwcHEQbt+wD8/e34A/j5+hYDBfX9CPjyBPoRCfwA7gP6/vn9/gsCBv8BCAP/APn37OwD/P/0BQMB/woGCf3/AQsC//cM/gD1DAYRAQQCAAsE/woFBfL3CPryBAj9DwX/9/oBAPcPAgMFAvv3Bvry+/oHA/8C/v33AfcDBPH/BgEGBvwD/PwCB/bzAAD9AP/6/An+Bwb5A/jzCAn/AwIDA/j///z8//wBAAsFAwMFBP/7//77+Pn/+f////QC/wr09gYEBP8L9QD1AvgBAwYE5Q3q+wcAAgr8C/YI+f8LCAcBAv8PAfz+Dfry6/j6AwcCCPIN+ALx/ATo/gEGDP8K+Q79DAMO/QsH+wjr7vIK+Pj39/f+AgD7/fj2CPEFAfwA/Pvy/AIOAfYG/wn1+wf//gT+AwHx7gMPBAEQAwgI9/f6AAIJ/AkD+wEHA/4G/f0ODgUF/AX4+gD+AwEI8gsABAYKBfsDBwQBCfn8Af3/BAb7AvUAA/r9+vsMDgQACPz9//r3AAUABAX5/wL+CvkG/AD1BvkD9QAC/fEMAgb9+QMAAvgE+/YD+gEKAwv7A/QK+/wBAvsJ9gYMBggD/Pz6CfcBBgn7AvwL"],
    ["septic-arthritis","health","/vT4Avjo/wgA//oD9QkH//8BAALx9An9BfIEBwbzDAoZ7AUNAvTp+vj5AgXu/wX79P39/gD7/gEGCPYICAH/BwD++AEJ9Pb87vwACvX+/vQC8Pzx/AL/8QQAAvMO/vHxCAD4B/UB+wb3BfMH//oT/v0A/vr9BwD0Agf//vn2/f4H+v4C+hIGCfMB/wD8APT39gH5DgUEA/779gL8EQP79f77AAADCfgEBwD/BgAI9gAHAwIE/AMG//AFCgIH/BQRBv8I+P0IBv8DCwQEA/v/BQcCEgn/BAUF/gL5BhD9AfEKBPoB9fAAAwf5+wH7AQD5Bf8B+Pn+Agv/+/77/fn7BOP67AgD6f8G7QHwCQXjA/X4/v8N3gYC+PsC/gYDAAYNFO0D+gf98vz+/wP+Af79/gQGCAUJAfoJBALzDQH+/P3//QL6/vf5CQMAAgT//vIC+AUD/v35+wf/Avj9CvsHAPv39AkJ/A739wECCv39Bgf7AwH1+/kH/QoNDPYC9AT29QMHBgkCB//2+AD0Cez4AwgDAAIBBQX6//sKCQgA/AYE+gf/Dgfz//sE/f3/+AX//vv+/QAHB/L5BAD/CPb6BPr3BQQHCwYL/Qn4AwD8BwL3BxEO+QMJ/v/7A/4ABP32+wP7/P0CCfgD9gQHAggBAvz/7v8J+/j8+v/++Pr9/AD/9wIA/u0I/ewD7QsBBAf8AwMD/vgA8/0F9gQB+voOBw/0BQQT9/T+AgH8+wMBBQPzB/33Dvv7/xEB6g75BQoA8/wO/AD08f32+woE//Ly+vsDBfUFBfH4/vYB8gj/AP4IBf8G8/z5Dv0I/wwH/wAP7/8N/uoE/fn4Ef8DAPcLBfn6Bf8BBQUDAgfu/AkD8/zxBvj7BA4H9fYAAQEJ/vz5CPwO8gUD+/0FCgcJ/wP39RIFAQADAAr4AwQTBgT5BwcBAQP7BQb9AQkNBgUC/P34/gIaA/oBBP8E//r4CwAEAgUEBPn4/QX5A/kB/wUC/f8F+vj6AgIDCPwDAgMABf/6"],
    ["deep-vein-thrombosis","health","+/z9Awvl8Qnw9fEODPwCBPz6CfT+DfwDCOP6Df31BBcQ/wrxBvnjC/759/73+wAXAfz1/gQJAPsCCesCBgUM/fj1AwIQ9Pz19Pj4+vHz+AQHAwf5DPsA8wT++f7z/AX1AwAE/Pb79Qvz9gQGFAAD+/T0/QEG+wbxBP3/AP/4DPj//P0CCQIPAv39+wf/AgQC///8BPsBBPj/AAUKBv/9+PgC//oJ/wX1+Qj9BQD//wIECgH7AQH9BgkM+voF9f4OBgQI//oG/wH9CwAG/QAA/gb/AwT5BAH7Av/+BgACCAP8AgUK/Pn8+vn0+gn/BP8JCfz+/QIGBff+B/wEAvz/BPj9/wIE+PsH7v7sA/v3AfoB9wv47ff5Avzt9xwHAgERDOoF8gb6/Q32CfwDDgINBRAHBPIK+QL6EQzyAP0GBQ7/9gMEBwLu//sL+/wC/f8AAhD6BwEM7/oA/Pv2B/0B9AQDAwbu+/oDDPr/Cf0HAgfxA/cN+gP9+wMFAvX6/QgC+v0F+wsGC/79AAMJBQv3/QIE+AT8BwH4BwUNAxH9Avn3CPz9CAX0AwMBAw4EBAIH9gP/A/wDAvj4CgMD+fwBAgEGAfv/AQz1BwX5/QHv9gUF9QQLAv4DBgcAAQIEAQ78AAQBAvj4AAECA/0I9e73Bwb5+gP5DA/+9wj9Af4HBPn0/fcGCQL4A/7/9hAF+PgK9fj/+fMDBQwM6vsS++3+Bfz1CPAH+egHAwfrAxAKCQkH+APx/ADrBfYO9vYF/wv4A/QG6Q379gH3//nzBfUE9wYJA/8J/g3/CPjyAQT+A/H/+AEA/PX0CQP/BAUH/wQD7vj9+wf9BfcGBwEI/QQJ9/nuBvUL/QT7/PoFBQECAw37/fwGAvf+9P74Bv4E8/vy9PgH/wYBBfoBAwUJBgH8/QAJ+vv9APgBAAX3/gL+BAj0BAf99wD6BAMH/AYGBgEKBgL/A/7+CAn++wAK+wAH+gIMAwX/B/j3AfQCDQIJ9/8C/f74B/v7DQgMBPUBAf/5"],
    ["pulmonary-embolism","health","9gPrAQXx8wLy8/sEAQTzBwQNDgTxE/4K/w8KDvb77/8N7gQFFQsC/wwM/vsCBQIQ/gIKBRX+8vIC+gL//QP+FPP9AfYH/wL+/P31BQMF7PcFAfYFBP7xCvwL+gMI/BIECP/6ChYECfb4AAoJBusHAfYE/PvqCAYA/AgG/A7yCgH9AAP3A/72Bf8F9wQCBvgF/v8GDAAA+f8D/vwLBggG/gcKCf8B+QQABgL5AvsN+Pf3/fv+Bv8QA/X6//n8+v0BA/8C/wT//QL4BPr+AfsDBQEGCgIFAP/5/f4D/wID+wL3CQMADAH6CQED/P/4AgMABgn8BAP7Aw0AA/sIAwoM/O/77AUF4wYG7fr3CgMG/AoI/Qv9+f73EAX4/wf09vsHBe33+A7y+/wJCvL6A/4FCPwHE/3+BOz2DAz/AAHyCAP6+AsBCvjv+vT+7QMD++778wD8Ev0K8vwBAwv2Df8K/AAL9gYC9gEA/PoKAfb6CQP6Bfb++A8M/fkKCPwB9gb9Af8F/AgE/gPv/gP9BAT9APoD9QkBA//3A/kDBgoABwkAAgX8Agj8AwgJBg4FCvb3+/r8AQQAAvv3BQsJ+QIKAQL8+vMB+AUD/wIDAAb9/QQNCBIPAAoEAP37/PgCBv8B/AMEB/sD/P8H+P4H8QUB+AP2/QUGA/4C/AH6BPwM/QD1///9AuL7+eb99Af6Bfb4BA/8+vQL9wMAEQIF9f7+BQfxBfcU//8KCgPzAQkH/wfwCwwCCBT5+P0H+wTz9w4D9/EJ9Pz6A/7zAPgTB/72AvP9/Aj9BvkDBQIT8QQFEgj8EvIFBf8L+PzwCQwD9Qz69w4ABPUGAvz89wwABf4EBgEEBP8C/vcI+wT3AAwI/AIA+/z+/gT1/vf2+gEM9wf4Cv0D+wMI//v6/P0D/gH7+PQBAvsHA/gD/wIEBAP6BAH//gL8Cv////cHCf79/wkABgMKC/sIAfT89wIADgkA/voA///7APv5Afb6CfwE+vsB/QAO+/n4+wEF9w4DBgz7"],
    ["altitude-pulmonary-edema","health","6/v/Gfrw+//09vYAAA309gMD/g0E/fn+/fsaBQX3+AoCCwsIBfkBAgQAAwIB9/38B+n6CP8ECwAECPkIDQUMBfoFBwf/9wcJ+gYMAfcP8AzpDQMH/An18fb5/f8T+goBDvXzCf4A+vMFAf0FCP/8BPoLCPYCBgj4AP0F+gMFBf4CB/b2+QH3/ez8AAL2BQH8/gQIDwAD//346Qb8+AwLAgcFAwD4BwL9AQIE//kK9/3+9AH5+gADAPjvBwkIAQIAAf0FBff4+fr09gMC+fsFAwILCQoM//sQ/goB9fcCAAj/Av0AAP3//AD4/fUF+fn5/v/3/gYFB/0GBvoJ/v/5Avn59xEA7fcI8+/9/PUM8v75/v/2Cg7yBP74EPr67eYBCAAEAAH1DwL/A/z1+AL6A+378Qn6BwH3EAD3BAL0AwD1A/UEBvQI//z98/P3APT9/AsMFPsA+fX//gX8DAAD/wEH8gQO+gX4/PcR9/oDAQH6+PP2AAMUAv8E9w0IAwIEC/32+PoJ/AL3BAED+gT9A/r/+AwGAPoCDAD9Bv8OCP4JAgwB9v7+CQoBAAAECwT3/PL4/v4BBgD0/gUD9/oJ/Q30APQA+wwG9gMABAYBBfwFAwgH/gUD/gAJA/31BgAD/fUACgcC9QQEDPkK+/wBAf8B8goOAvwA+QP0APv/BQH5/e4I+AL5//b++xALC/MF//kMCAH8AQcIBxju8e8D/QQG/fYH+fwP/QMA9QL/CwgACQACAf/2CRALBPv0/vkI8wP7AAf7Hu3oAv4G8gfv/Pn5/gf89+0C/fgA/wvvBgQJEQANEgH76wP7BQ8KCAT/8/718/L+/vgFDQ/5Bf8E/vr4/vgA/gEBAAEMBAUBAP0GCAT8CfcB9wX1+P71/gf9+gABDwMIAwEC+vkFBgUCBPv9BwH4/gQF/P0H//39AAENDAwCBwP+/v8D/wH2BAgDAQYABAYGBAAD+QUD/QD8AvYHBvsFBvL9/Pb8/QQDBPYGBAMGAAgA/Aj6Afj7BwIE"],
    ["rhabdomyolysis","health","+vj4A//mEQL8APgBAQUA9/QF//vq/Pv79gH3CwH7BQIJB/v7AvgGCAv1+PINA/z2/AUG+vkBAvwJ/fcSFAL//gT1BvgQ/wPzDgUBAAQM+wED/wsC//32+fcBDfkDEfwC/v71EQEEAQr1+wj+AQQAEvv6CgAH+QQDDfkC7g8FAuv7+wMMAP39/foD/wcI/QQI8/kA+/oEAfULBwj++/0IAPgJBv0IAfYC+wsDBgn+//EB9vUA9AD88gMJAfPyBQYDA/AJ/vL2+f8GBvz7+f75+PYQEAMDBgMIAgkW9wQGBgH/BwEDCQIB+gX4Bv4H9wIA/PX39AAFCvYF/gH+AgX79fT79Ar19f4S+gPy/vv9/On/CwMG+/QI+Pz6BQDz/BILEfj9/AcJ8BT+9QPvDQgCAwoCBAkEBP4LCvsJCwv/+vUKBADzDgP4AQISAwAGA/T8//v8/gH+7/b/DwL39Qj99/sE+wr6EQP28PsABAL+/wn5/AzwAhL/A/cB/ewFBwAMAfoI+QX9BvwF+vsEAfsSAAUU9gfz9vgC/goNBQoBAwD6Dv8C/wIB/vsHAQMBAgD2A/r9APgD/PL8/wEBB/gEBQP3Cvj4+gMACgD7CwAD+/73AgkG+QYI+/sCCAACAff8Bf0JBPv7BQgDAPQN8vP9+//8//8M+wr3/Qj7/voGBAH1AuwF+eEMEQL6/P77+vr67P/9/vAH+fr7CQD89vT8+wT7AgAA+fkK9PoH+woHCvkBB/4D7wzy+wb1AAsJ/Av7CAAF/RMYCAL9AADvBgj59/MABvr+AvL1+wQJ/RICA+gECgAG9gn8+AP4+/X6/fwO+fgO/gr3BwIGAQf+/gD8+wcC+/wE/ALz/f0ECvcCDf4EBvAHCfUD8gP+CeoK9wP5+QMI+vwF+wP9BwUBEPv6Bwf8/gH+Afzy9gP5+/X5AQoI+gYC9P4HAQIDBPv/DgL+/fsDDgICA/sBCwcAAAD49v8HBf4A+/kJCP8BA/z6/AL99wD6+PkE/AT/+/oGBfT5"],
    ["bowel-obstruction","health","9PX9CvrhAgrrB/r69Pb2CPb3AAEE8fr9E/4HCv/9BPr1+/cF/fb1DwD++wYKAAP9CATz+foF8Qz8DP71Bgb3Ff0R+QIK8/0LBwr+/PT+7PT6/vsI/wD1Af7/8P35AP3zDwn/EPj6AfcJAwsI+wT2Dfz4/vzvAf/8+f//+/L78fn7BPsC/gQF/PgIAhAF/wQB+AMPEfILBfUGAQf7C/0HA/z+DvwD+/X7Afz/CAkWAf8D+An8Av4I/PoGAAr8AgQIAP0A9gYEBgEB/Qj5AAQN+f4CDAz5/gQB+wv/BQUA/PwCCPr+AAAIAv32/fsHBAMACPj8BAEHDPr++wL69/oCAfLu+RH26P389f/y7fME9v3rBP0F9vXx8wUP+wj/Afv9AQD4B/0F7hLy+gsBEfH4+AoH9wH0/fAA/Az2+QkH7A8MCfsF+fwQBAgDBPkC+vr0//z+BBH7AQr3AfABBQcAAQX8BAoJ9QX5/QkY+fgA8AMNAfv//PX7+AT9Bv79DAIA8f75/gT+BfgBBwIJBwEF/PQICREADPr+Agf/BAT++AMD/Q0EAPz3BP4AAgr4Bf/w//4J+P4DCf0C/QL+AfT6/w32CAP/BwICBA79Av3+Bv36AAcJ+goF/v8FBwL9BP/+/wcE+ff/B/sC+gEG/wEG/QP9AQr+Agr9BAMB/f8EAAj9CQIFD+/78ur39v37/fYMAAkDAP70BAIBAhAJBAv+AAIA9wD4CAEBAAD/Bfb36/8P8Qr99w4CAQL38/4LCf/sCggC/Q4B8wgCCAD/A/cCBfIC/wkB8/T49QMO//cEE/8P/w/+CAEG/wcECgIJ//z//QEYBfYJ/f4IBwMD/Pv47AgA/wb/9v/8+QADAgkG9v/4/QEFAA8A9wQU/gAHCQj4B/cJ/QYD//zt8gT9/AX39QfwAv/4Bwb7+QX/A/n+/AL77gv7CQP99vkABxH/BQUC+QQH+wX/Av728/7+Bf0GCggCAgAB8w8AAfsHBQv9BP0F/f8PBAH8+//6Agf2BPsR"],
    ["cellulitis","health","/fQGE+ru8PsA7QfuAAb+7goF+gH9CRX/A/v+Bg3/AQAU8/70+wD16gXs+/7v9g4G/P8E+f76A/j2AwT7AAn9C//69vMGAgAH+/38Cfn8AwUD/QIKDgQHCBAC/gX///r6/gDzAfwX6/78Bgn6//oHAAMJAv3/CQIKCgL0+vgABwMM//0EBAMEC/EF/wj9Df4E+v7//wAC/gj9/gIKBf7x+An9+wT8Bf0MAfoDBfn4AQUF/wgB+Q38B/X8+/0OBfsQEfwEB/sGBQD6AvgBBwYFAAMDCP0EAQELAfX6CAX/8fgQB/v8//UDAAf6Bw7+CAMBBQME+foI+wH99QQAAf/0B/j0/wL99/4B8P/1+gb+AO/x/gkA7QYB/+/x+BIE/wgNAgP+6BUA8/379fMCBPr/BQv1AQX8/QP1/Arv/AoK//L9+QP9EgD3APIDAwIH/vT/CQoAAwYI+vgNAvsIAv3yA/78+Q3xBwAI9u8N9wn9CP/7AvwDBQEJ/hEHAesK/AfuBQb9/RQAA/z2BQYF/QABBgQBAPz9/gX6//0QBwD77/v+AvcCAwQFC/4CBgwD+Qj7+vj6APYB+foHDv/1BvoBDAH+AAT4AQIIBQvxCAX2+An9DwYFAwcLBwoBB/oCAwD8/wEABfX8+vr9BgMH9vz5CAD/AwEFB/r2AwT9CgYJ9fny9gAG9+n/+PX3AfkIAAX3CQD4AuYKBvj+9fYGBvkFCw8F+//89/Hw/eH0B/TyCQgC/wnwBv39/RMG/Pj2BQMRAvj6/RUC/fb59fwS8gH8+gEQA/r8Bv4GAQMD7fz5//sABPQJ9AUBCPn6BQcIAwEN+QgJ/QAU/Pv2BAr1+/kDBf4JAPz8Bf769O78BAAE/v3+/gIK+Pr/9f0DDQgQAv/9AvsCBwn8/QL+/AMKCAED/wQGBv0CBwIEBAr/CRAEAAwE/Aj9/w8B/wQN+AL6+vwD+wMNCPoEBwH/AwIEDQH5AfQHAfkH9gf+/v0AB/kG/goGBP349wAC/AP+AvwECfsC"],
    ["botulism","health","7vz7/u7/Ag8GBPUC+f/sCPPt/vP8EAT6CQgHCvj6/wj2EPj99AQO//QG/wj2/wUH/Pvx/P/4Awrv+wH3/PYEBPsC7vz7BgYDAwL7//sE/PT/C/YB+AzoAhD8AAcHA/7/Ev4I8/QDCfb9/gMG/QP6B/z//PUFCQD9//v2AQL2CPoS+Pn6AAr3CfQAAQP9BAT39fwPEAUK/f8GDATwDQX/+gb/Dvr7//X7BQb4CgMD8PkHA//5BvkGCgT3/QsB/vQGAwn9CQcMBPv8AAvy+foL//r8CAH5AgT5Awr1COv9AP0C/vwECAn/+fj/+gIABf78CP8CCgcECf36BQoGAwQDAuft+Av06/r0B/v4+wHyDAL/9wjzDgrv9/rqCQb4ABML//P/APX0DgHwAREL/gsMBf8IAwcE9wQH/v73+/8B/fgS/Pf9Bvry9QMBAuwC+fb+AwEG+RAGAPAB6/j5ARAABQ4BB/D89gf5/gYJDAUH8QkQ/vz7BPbzAgMI+AALBP34Aff//wwEAwP1/goFBQIJ/QD8AQvx/QEC/Aj9/vz9AgUK+AP+AwAKCP/8B/76+/r5+wQL+P8FCvf6/gEB+QD+BP4B/AYEAvv4+wACAAEAAAb+//0F/wX48wIL+QgCBQD1AgT6AAIF/gYJAwsG/wEB9foB/gIGCwIA9/j4+QD4+fjnAQMH6fIG/wEE9fr6BvkL9vD6/fcGA/b+AAwQBPv/D/f/+PoBCgsB+gYBE/gJ/fb7/P8MCvwHCgMDD/jw/AYOEAIB/AsG+PT7+fP8+/0GBPgN9f/3//b6CP4B+wT/CPkMCfMK/P/5/PryAwT0//8DDAP9+AYA+PcJA/UEAf8G9//97vr7EQT/8w/8B/4CBAX0/gcM/gMI9wUK+u4P/QYF9/oMAPn4B/3/9/n7Bv30/gfzC/4O/PwH+/r3Bv8GAQP/AfgKAwP89PgD/vf6BPgAAfMFDAEGAQT8CAcQ9QAJAAT6AhQA/PcB+Az8+QABAPkA+fsJB//69wIEBwQHBAkB"],
    ["dengue","health","BePv/vDt/vQA+vMK6fwF7AL8///zCwzs/vn5FQvu/QsS9/cKDffvA/z1AgP+/gUI9/38/QsG/PYO/P4EDP0I9v74+/EJ+PYB+PQRD/7x9fsNBQ78/QkM6gHw+fz6BAD4A/v//fv/+vzrAwb7Bv4E/f8DAfb19wPyAQX8AAP+CwAI8/wDAQf4BQD/A/T///z9+Pf7D/sK+gb3/AgDAwj+/AIA//wE/fb/CAkG//4F+Pr8CQP/8gEE+AIFAP0G8P4FAgMD+wQF+/z7AfsLDvwDAfkDCP77AwMBAf/6/vwHBAQC/QAF+QEBBfsDAgIACP8B+QYBBgL1AgH8BQQEAv0ABwHv/Pr47gsDAPX2B/MJBPkACPz45/8I9wYK9wf2+QUSDvwP/vcC6AT88/8CAf/7+fH2+fn7+wf1DAPz+gn/9vsP/f/3CPwK/uj0/gn5/v30C/MN+gD8D/gP/vv3EQX27Rb8+wn5BvoK9gj+9v8FCv8FAQX99P/98Qn//PL3/gL2CPkNAv8C+wD8+QPz+fsCAwf89wkC+/sB9PgFAAj+//z58Ab+BQr7/wP+AfgHBAEAAwj9BPEE+/z9AgECA/sICfoHBAcDBvT+/ggFBwsE+gf6/QQF/f0EAv8I+gcI/QH9Bv3+9//8AQcKAPMKBAr+CP/+AAEIAvr9/Qj89vME+QQP7f308O4I/f7y9f7zCgT5BQEB9O//EfgF/v8K//0IGBwCBP34/+v7+Pf4/gH/AADl+/jw+gQG/woA+gECBf0CCP32/gjxDgTp9wcK/An87gT5+/T8+gADEPsC/hD09fQGBvUD/gL6CPMCCPP+BQT5APcD//0IAvwH+gb89fj4Cfz9DwME//z+8vwB9/v7+gED+/8K+/r9+vT0FAQJ//b7BfwC+gIN/P0I+gQC/AT4+wcHA/74Av369QkBAQn3CAcHAQoGAggB+/sCBAEJ//z/+f0CA/8FB/0CAgQIC/QB9QQAAQD19QMCCfz5BAUHAwcAB/oB/wEAAv7///r5//37"],
    ["malaria","health","AukJ8u3h/gAH8ez89hAI9AUHAP3zCv/0BAP/8PsD8gkM7BELCQDtBP7+AfUVBgHv9/35/wgB+/sC/f4MAAIJ+f/xCgEJ+wT/6+0S/wv6+vcEBBH+/f8M/AP5/QEL+f32AQr1+QEBCQj5CAj5/v36/fT49wPy+gL5Dvf/AgX3+xEF8Qb5/Ar8CfYI+fT+//r7Af/3BwgD+wHt+AAH/AL5+wQA/PgAD/v9A/wBAfUAAf8E/QQE8v8G+fsBBvwC9gMBBP0GAAH/A/78AQoDA/3/9//9A/v9/v36CQsGAQQDAfcHAQP+9v8DBAb7AAIBAQAHAwUDAQgDCQj8AQQCA//+APPvCwfr6AX8AOb3/+UIAPD5CAUEAA0H9Af89vsD/vb3DPAQEgX2+Ajv+wUFCwML/BH49/n9AxD7/PT/CgwBC/cA/AH6C/b4/fL+Av8O7fX+AwQEBfcEBvoH8wQEAPsF+Aj/Avn/+Q0I9wMa9fgA++37+/EL+/kB8wT4/wn++fYEBPL5BfsA9wUE/QX5CAr+CPoCAAsBBAgF9fgCBQj+9/wH+/v++gL7AQQC/vMAAQD/+fgBBfX8/fcABgf+CvsBAAH1Cf4A//gCAQQEBP0B/vn8AwQE/v4L/Qj4Cf34AgD/BPn6A/z/AAYBAv0CAQEDA/X/Bf4E+/4EBQEE/gv7/wT98wD9+PMF/wT03gTyGvry/QT8/fn8BPABBgAH7f3+DQj6HP4D//QC+Pz5+QcM/vXyAvL1Av7+AwH99Q8GAgntBPcI+fv7A/jn9wMIAvoD9wj4A/sB/RH9Buj++RT9/fsEAf4G8QT4DwMCAfoFBQD2Afv9+fD+/vQE/P/58/4HBf71CQD6/vwG+Qz97QYG+wj2APMIAAkBAvX1CgYC/Pz5/voF+wcH/wAFAP/zAf4C+QMDA/vyAwT7AQgHAgvzBf4AAQQICAP8+/wCCAkKAwT6AvoHBfcAAAoGBgYHCAAE/gH+AAX2BgUDA/4AAgYC+wQC/QAACfoIAP4MAgf/A/z/"],
    ["sudden-hearing-loss","health","7gL2+wr1CQLt9/r88xgD/gUHB/8DCf7v9Pn3EAUM9P8I+wAJ/Q0CBBAQ8QP48AoHAwgBBwD7BgMK8u7+8vEFCPv++/vs+/UE/v0VAPH0BPoRDQP3//sB/v4EAff39gn2AwoD+Qr8BwDtBAH5+QMCCvb+CA/+A/r/+goBAwkLCvgDBv8EBgj6//r+AfwC7/wA9v8DBAID7QP9BQEJCAHzBv0D+fn7+ffvAgb7AfwAAAQB/wIE/fv2BwX/+wL7/vcF+vj99wIJAAH4Cv3/Afz99vny/gT+AQf5+///9wv6A/wG+wP79v4HAvwJ/QkL+Pn8Cg4D+vwF/AX2/vUGCQn7C+YB+wH5+g//8/jw9/wgCf8E/BAH/P728vv2/gn/B/MJCAMFDQETAQELEPQO8vQH+gEIBf35//n5Afv4+vvzCw/8//r57gbvAQcECwP8+vz1CwwC+/f8//oD//r09fUA/wsB/v0E9AYG7wL/8f75CBL8AwUR/wQDBAf6+f4GDAoD+QkDCgMQ9//3Afj6+gL6CvwB/gYDAPD//gr+CAYL9wP4/gD++AYB8wQO9wAE+AH4Cf0D//v29Qb/AfwG+wEH/vgCAvcD/gT+/AUBAPz8AO0E8wUK/gEFBQID9/0H9AQEBfr6A/j6AAH9BAEC//b3AAMB/P/7BfkD9QT1BQYQBQbsBAb9BOoQAe/z+u0AGP/1+wUP+ff2//D5BgMS+QT49fz8BAL+7BH+/AH4DPbpAPkOBQQJ/vvtBQ0E8ggE/wEL+/n+CvgH/AL7+wL2+P8D9wEBAfnwAPL9Aw749woFCwcG+/cBCPD9BPgJC/j6+BEM+vwJ/QMA9QYEAALxC/8T+gQKDAkA/QID/QQB/PsE9AX/AwEABv75+QYABv78CwEI/QECBwQFB/0JAfr4+vf+9Qrw+wUE+/YJ/P78Df0ICP8I/QP+APwA+AQHAwoD+v7uCfYBAwkKBf8CBP7//wwJAv0JBQH9/Qv9AgECAwj6Af/8/wL6/gEF/Pr+AgP/DPYD"],
    ["angioedema","health","9/fq+vvj/wsB+esA/hoGAAH2E/7+/gr1AggAG/n18/YA9Pz9//r++v339fgE9g//Cv7oBA39/PcIDgT//fkH8vH/AQIb+Pf5+A/5A/wC+P/7CP38AA0G9fr///IMAv7+AgcA/Ajv8Qj8CPn6//0X//4K/f4GBwAD+vkB+PT9AvcFA/cJAwj5A/wEAvf+AQMA+gMBEP8GAAIICfwFDAH+CgEP/AYCBAcGAwP9BfgAA/38AgD3AfoLBP4ECvv/BgQAAQYC/wEDB/4K/gH+Af78Af4NDQcM/QMC+wj8AgECBAX4BwEABPsA9vz3BwEBBwz/Bfr08/sGAPoHAPYDBQX3/fML8Bn06QYG/vQW/PUAEPMI+QwA+gMBAQYKAP4G/gAN/PgBBQf7BvwCAQkNAfcIEfv+8wIBCQv/Au39+wH7/AH6A/r+BvkIBO8E/QsHDOz++Q4AAQAS+Pv+CPz6/AL16RD7/QIGBP8OCwT5+fr8C/n0EQkB8xQCAQb0BP4CAP8BEAj5/QL6/QP7+wT2+/z7Dfn7ABT79wMEBe74CAIQAAADAfn//Qj8Afr0AfkJBQYP9QAF/woE/wP2/P37BAAD/P0M+vv+/wP4DPYBAwIEAwb+/gkCAQUKA/b8/AP8+f8A+wL/CP/79wX4CAYM+P/7/gYDAvv7AQD9Av35BQP+Cgjw7vX/+/cK///48f7uAg7wB/cQ+gEEA/0G+vsIAv8CBwIB//z7+wL7/ezuCvT/Bvwa//YC//v6AwgKD/ns/QEH8PwDBw4G/fL2CgL/+vf4+/8A9wH5BgL69gX88f3z/P4DAAL4BfjsDPgKAPn9+hP/+wb4+gcR/fv09QX/7gj89AgD+AgFAAQM7wEA/wkAART4+AITBAf//gAHBQYP/PwCCAT3CP4G/gjwBfr99gkF/AEHCPUJA/4A/v0M9gT8A/T2/fb8/wwD/wj++wf/+fv//w0IBP/8CgT+BPsJ/f4G+/z7/f8A/v4ABvX8BPgIAgICAPr4/QX/+AH7+QYPAQAK"],
    ["ovarian-torsion","health","8fX1BvvkBPfzBe4C9/j4CAUKBgPj+P/uDw8HB/kL+QoK/P0GAf34DPz+Cwz/+QL7Bgf5B/gI+wMACewCBAX6AAYRBgH4A/wHBQMF+/H67/kI9vX/Bv35/vz2+eMFBAwGBPL98/v0/AL7AAcK+PYBB/r+GP/wBAII/foK+AsEAwX1BQEKBv0JBv8CBP0CBv/7+AT3BQQK+fwK/AIICAAABQP5FwYBAwn9AgL0Dv8H+/UI/AT3BAEB+/3+/gL78v4AAwcC9An/BQYD//oC+vsEBAL+CgIB/Ab5BAMD/PgC+gT0AQP89AH/+QX8A/4A8wD69/H+Bf8E+f/6/gEI/wj7Avjy9vn/5AH97P/s/f399foFBxAK7gEC9AAPBgwHDPsHFfX0BPoJ+woD/PsOCQD1+QD5BPwJ/+f4+wvvAQoOAggHDAj9Av//BwEB/QIG/vr0+f74Cwf8+v0F+ALvBwAI/gcM+AUF+f3/9f4O//ME/wP2Bg0I8AQF9g//Ce0J/wv+9QEFBRH/+v0GAfUGCgf3Avj/9AwFEPb9AgIGAQoB9Qn/AA7//QH+Av76Agv2Avr/CAP8//gJBwD8BQMG/u74/wT8/Pv/AAL9/xD6Bfv7AQX4+gMQ+v0HAgT+AwICBQL8+wQD+vn8Cv39/wACA/n9Av3xAQT2Af7+//8BBQIM+QT68vL4B+b19PoA+PrzAPz8BREJCOL69wUODw8NAAQEAAPs9/8KBwEHAPwFEAL8AAUQ/gT8DPjx/PkU9wYH+wcFA/sQ+PIG/gUDBwUI+/H1APnz+P0A/v8NA/v75gAPFgIGAQMABf76++f/BAX4/wQO8AYUCfIFBvsRCA78DAQFA/oD/gEJAPb5/////wIN/AAB//MDAwUCAP8C/QkO//gDBPoKBP/0/gf+AwAA+v3+/goDCP0CB/z9+AIF//z0AAIB+wf//v77/PoG+v//CQD79wYQAwEBCP4FAPoHBQcHB/4BBAH6/gUAAP8FBAYC+/0D/wECAP/4BwMB/QsBCQX+"],
  ];
  // END GENERATED EMERGENCY VECTORS

  let emergencyCodes;
  function emergencyMatches(vector, domain) {
    const norm = vector && Math.hypot(...vector);
    if (!norm) return [];
    const width = vector.length;
    emergencyCodes ??= semanticRoutes.map(([topic, field, packed]) => {
      const data = bytes(packed);
      return [topic, field, new Int8Array(data.buffer, data.byteOffset, data.byteLength)];
    });
    const matches = [];
    for (const [topic, field, codes] of emergencyCodes) {
      if (domain && field !== domain) continue;
      let score = -1;
      for (let offset = 0; offset < codes.length; offset += width) {
        let dot = 0;
        for (let index = 0; index < width; index++) dot += vector[index] * codes[offset + index];
        score = Math.max(score, dot / (127 * norm));
      }
      matches.push({topic, field, score});
    }
    return matches.sort((a, b) => b.score - a.score);
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

  function rowTitle(row) {
    return row[0] ?? row[1].slice(row[1].lastIndexOf('/') + 1).replace(/_/g, ' ');
  }

  async function unpack(encoded, query) {
    const needed = query && new Set(query);
    // Stemming strips suffixes except for the ies-to-y rule. A retained
    // prefix lets a browser skip titles that cannot produce a query term.
    const prefix = query?.length && new RegExp(query.map(word => word.endsWith('y') ? word.slice(0, -1) : word).join('|'), 'iu');
    const stream = new Blob([bytes(encoded)]).stream().pipeThrough(new DecompressionStream('gzip'));
    const chunk = await new Response(stream).json();
    chunk.vectors = [];
    chunk.semantic = [];
    chunk.vectorCache = [];
    for (let index = 0; index < chunk.records.length; index++) {
      const row = chunk.records[index];
      if (row[3]) {
        chunk.vectors.push(index);
        if (!row[5]) chunk.semantic.push(index);
      }
      if (row[5]) {
        if (prefix) {
          const title = row[0] ?? row[1].slice(row[1].lastIndexOf('/') + 1);
          if (!prefix.test(/[^\x00-\x7f]/.test(title) ? fold(title) : title)) continue;
        }
        row[0] = rowTitle(row);
        for (const term of terms(row[0])) {
          if (needed && !needed.has(term)) continue;
          if (!Object.hasOwn(chunk.postings, term)) Object.defineProperty(chunk.postings, term, {value: []});
          chunk.postings[term].push(index * 16 + 9);
        }
      } else row[0] = rowTitle(row);
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

  function rankPart(part, prepared, asset, limit, exactPass = false) {
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
        if (exactPass && (weight === 5 || part.records[index][5] || part.records[index][4])) continue;
        let stats = lexical.get(index);
        if (!stats) lexical.set(index, stats = {hits: 0, literal: 0, strength: 0, body: false, bodyHits: 0, leadHits: 0, weights: evidence.length || pediatricHealth ? new Map() : null});
        stats.weights?.set(word, weight);
        if (original) {
          stats.hits++;
          if (weight !== 5) stats.literal++;
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
      if (exactPass && stats.literal !== query.length && !support) continue;
      if (stats && !stats.hits && !support) continue;
      let similarity = 0;
      if (vector && row[3] && !row[5]) {
        const packed = part.vectorCache ? (part.vectorCache[index] ??= bytes(row[3])) : bytes(row[3]);
        similarity = vectorScore(vector, packed, Boolean(stats));
      }
      if (!stats && similarity < 0.37) continue;
      row[0] = rowTitle(row);
      // Some preserved recipes have page numbers for headings. The time
      // table names the exact recipe even when a page covers multiple foods.
      const recipe = asset.format === 'pdf' && !asset.restricted && placeholderTitle(row[0]) &&
        row[2]?.match(/^Recommended process time for (.{3,80}?) in (?:a|an) [^.!?]{1,48} canner\b/i)?.[1];
      const title = normalize(recipe || row[0]);
      const archivePath = typeof row[1] === 'string' ? row[1] : '';
      const dictionary = /(?:^English-[^/]+\/|(?:^|\/)(?:vocabulary|dictionary|glossary)\/)/i.test(archivePath);
      const sourceHeading = titlePatterns.length && !recipe && placeholderTitle(row[0]) ? normalize(asset.title) : '';
      const conceptTitle = !dictionary && !/\/[a-z]{2,3}$/i.test(row[0]) &&
        titlePatterns.some(pattern => pattern.test(title) || support && pattern.test(sourceHeading));
      const deliverySection = deliveryQuery && trusted && asset.format === 'pdf' &&
        /\b(?:pushing|second stage|stage 2|giving good care during labor)\b/.test(title + ' ' + sourceTitle);
      const postpartumSection = postpartum &&
        /\b(?:postpartum (?:bleeding|ha?emorrhage)|birth of the placenta|bleeding after (?:birth|delivery))\b/
          .test(title + ' ' + sourceTitle);
      const exact = title === phrase || title === prepared.original ||
        title.replace(/^(?:how to|how do i) | page \d+$/g, '') === phrase;
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
      const repairTitle = prepared.repair.length > 1 && title !== title.replace(repairAction, ' ') ? repairObject(title) : [];
      const exactRepair = repairTitle.length > 0 &&
        repairTitle.length >= prepared.repair.length && repairTitle.length <= prepared.repair.length + 1 &&
        prepared.repair.every(word => repairTitle.includes(word));
      const titleMatch = !emergency && !dictionary && (!question || matchedAnswer) ? exact ? 2 : exactRepair ? 1 : 0 : 0;
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

      const titleScore = titleMatch ? 125 + 20 * titleMatch : phraseHit ? 29 : 0;
      let score = titleScore + lexicalScore +
        (coverage ? 95 : 160) * Math.max(0, similarity - 0.24) + typedScore - (row[4] ? 19 : 0);
      if (emergency) {
        score = support ? (exact && !question ? 58 : 0) + Math.min(lexicalScore, 48) + 1.65 * support +
          22 * Math.max(0, similarity - 0.30) + typedScore +
          (trusted ? 39 : 0) + (emergencyReference ? 16 : 0) + (conceptTitle && !question ? 105 : 0) +
          (deliverySection ? 52 : 0) + (postpartumSection ? 70 : 0) -
          (maternityReference && !deliveryQuery ? (pediatricHealth ? 50 : 25) : 0) +
          (pediatricSource && child.test(reference) && symptom.test(reference) ? 12 : 0) - (question ? 30 : 0) - (row[4] ? 19 : 0) :
          Math.min(score, 34);
      } else {
        score += 0.95 * support + (asset.critical && (stats?.body || similarity >= 0.43) ? 5 : 0) +
          (readyReference ? 18 : 0) - (advancedReference ? 22 : 0) +
          (conceptTitle && (!question || answerConcept) ? 130 + Number(Boolean(recipe)) : titlePatterns.length ? -48 : 0);
        if (language && (' ' + reference + ' ').includes(' ' + language + ' ') && phraseReference.test(reference)) score += 90;
        if (seed && support) score += Math.min(36, support / 2) * (stats?.hits ? 1 : 0.5);
        if (pediatricHealth) {
          if (maternityReference) score -= 30;
          else if (pediatricSource && child.test(reference)) score += 25;
        }
      }
      const matchedTerms = stats?.hits || 0;
      if (exactPass) {
        const longest = evidence.reduce((length, phrase) => phrase.every(word => stats.weights.has(word))
          ? Math.max(length, phrase.length) : length, 0);
        score = stats.literal === query.length ? 1000 + score : 100 * longest + support;
      }
      found.push({row, index, score, recipe, titleMatch, matchedTerms, fullMatch: matchedTerms === query.length,
        literalMatch: !row[5] && !row[4] && stats?.literal === query.length,
        bodyMatch: !row[5] && Boolean(stats?.body), focused: emergency && support > 0, trusted});
    }
    return found.sort((a, b) => b.titleMatch - a.titleMatch || b.score - a.score || a.index - b.index).slice(0, limit);
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
    const title = displayTitle(asset, hit.recipe || rawTitle, locator);
    const archive = asset.format === 'zim';
    const destination = asset.destination;
    const href = destination.split('/').map(encodeURIComponent).join('/') +
      (asset.format === 'pdf' ? '#page=' + locator :
        !archive && locator ? '#' + encodeURIComponent(locator) : '');
    return {score: hit.score, titleMatch: hit.titleMatch, rankTitle: rawTitle, matchedTerms: hit.matchedTerms, fullMatch: hit.fullMatch,
      literalMatch: hit.literalMatch, bodyMatch: hit.bodyMatch, focused: hit.focused, trusted: hit.trusted,
      indexed: true, redirect: Boolean(hit.row[4]), record: {id: asset.id + ':' + part + ':' + hit.index,
      asset_id: asset.id, title, description: lead, source_title: asset.title, href, destination,
      kind: archive ? 'article' : 'section', reader_required: archive,
      ...(archive ? {archivePath: locator, archiveSection: heading || ''} : {}),
      location: archive ? 'Archive path: ' + locator + (heading ? ' · ' + heading : '') : asset.format === 'pdf' ? 'Page ' + locator :
        locator ? 'Section: ' + locator : 'HTML',
      license: asset.license, attribution: asset.attribution}};
  }

  const READ_BUDGET = 32_000_000;
  const BOUNDED_BYTES = 39_700_000;
  const EMERGENCY_BYTES = 16_000_000;
  const COMPACT_BYTES = 20_000_000;
  const COMPACT_INDEX = 125_000_000;
  const PREVIEW_BYTES = 350_000;
  const TERM_BYTES = 4_000_000;
  const READER_BYTES = 12_000_000;
  const SPELLING_RETRY_BYTES = 6_000_000;
  const SPELLING_LOOKUP_BYTES = 1_000_000;

  function impactBucket(word) {
    return (hashTerm(word) >>> 24).toString(16).padStart(2, '0') + '.js';
  }

  function edits(word) {
    const candidates = new Set();
    for (let i = 0; i <= word.length; i++) {
      const before = word.slice(0, i), after = word.slice(i);
      if (after) candidates.add(before + after.slice(1));
      for (const letter of 'abcdefghijklmnopqrstuvwxyz') {
        candidates.add(before + letter + after);
        if (after) candidates.add(before + letter + after.slice(1));
      }
      if (after.length > 1) candidates.add(before + after[1] + after[0] + after.slice(2));
    }
    candidates.delete(word);
    return candidates;
  }

  async function correctSpelling(text, vocabulary, impact, read, cancelled) {
    const replacements = new Map();
    const unknown = [...new Set(words(text))].filter(word => /^[a-z]{4,32}$/.test(word) && !vocabulary.has(word));
    // A correction is a fallback. Bound vocabulary and term-bucket reads for it
    // independently of the ordinary candidate budget.
    const blocks = new Map();
    let remaining = SPELLING_LOOKUP_BYTES;
    for (const word of unknown.slice(0, 4)) {
      if (cancelled()) return;
      const candidates = [...edits(word)].filter(candidate => vocabulary.has(candidate));
      let best, confidence = 0;
      for (const candidate of candidates) {
        if (cancelled()) return;
        const bucket = impactBucket(stem(candidate));
        if (!Object.hasOwn(impact, bucket)) continue;
        if (!blocks.has(bucket)) {
          if (impact[bucket] > remaining) continue;
          remaining -= impact[bucket];
          blocks.set(bucket, await read(bucket));
        }
        const df = blocks.get(bucket).get(stem(candidate))?.df || 0;
        // Missing, extra and swapped letters retain more evidence of the
        // intended word than substitution. Use frequency within that tier.
        const retainsLetters = candidate.length !== word.length ||
          [...candidate].sort().join('') === [...word].sort().join('');
        const score = df ? Number(retainsLetters) + df / (df + 1) : 0;
        if (score > confidence) {
          best = candidate;
          confidence = score;
        }
      }
      if (best) replacements.set(word, best);
    }
    if (replacements.size) return text.replace(/[\p{L}\p{N}]+/gu, word => replacements.get(fold(word)) || word);
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
        score += terms.get(term) * (phrase.length > 1 ? index.weightByWord.get(term) : 1);
      }
      return Math.max(best, score / phrase.length);
    }, 0);
    return (1.4 * total + 16 * present) / (6 + query.query.length) +
      support * (query.emergency || query.titlePatterns.length ? 1.4 : 0.65);
  }
  const decoded = new WeakMap();

  function rankedQueue(selection, query, shelf = 'all', budget = Infinity, evidence) {
    const queue = [];
    const routing = query.routing.map(hashTerm), primary = query.query.map(hashTerm);
    const exact = [query.phrase, query.original].map(title => hashTerm('^' + title));
    const concepts = query.focused.filter(rule => rule.titlePattern)
      .flatMap(rule => rule.phrases).map(title => {
        const termsInTitle = terms(title);
        return {signature: hashTerm('^' + title), terms: termsInTitle.map(hashTerm),
          specificity: termsInTitle.reduce((total, term) => total + (evidence?.weightByWord.get(term) || 1), 0)};
      });
    const pairs = [];
    for (const terms of [query.query, ...query.evidence]) {
      const keys = terms.map(hashTerm);
      for (let left = 0; left < keys.length; left++)
        for (let right = left + 1; right < keys.length; right++) pairs.push(pairHash(keys[left], keys[right]));
    }
    let routed = false;
    for (const asset of selection.sources) {
      if (!filter(asset, shelf)) continue;
      const {domains, discussion} = sourcePolicy(asset);
      const onTopic = query.focused.some(rule => domains.includes(rule.domain));
      const sourcePriority = onTopic ? asset.critical ? (asset.format === 'zim' ? 3 : 4) : 2 : 1;
      const sourceQueue = [];
      for (const [number, part] of asset.parts.entries()) {
        let data = decoded.get(part);
        if (!data) {
          data = {bloom: atob(part.bloom), lexical: part.route && bytes(part.route[0]),
            centroids: part.route?.[1] ? bytes(part.route[1]) : null};
          if (data.lexical?.length) {
            const filled = data.lexical.reduce((total, byte) => total + bitCount[byte], 0);
            data.titleConfidence = 1 - (filled / (data.lexical.length * 8)) ** 2;
          }
          decoded.set(part, data);
        }
        const hits = routeHits(data.bloom, routing);
        if (!hits && !evidence?.hits.has(part.impact) && (!query.vector || query.emergency || discussion || !semanticPart(part))) continue;
        const priority = query.emergency && semanticPart(part) ? sourcePriority : 0;
        let titlePriority = 0;
        const primaryHits = routeHits(data.bloom, primary);
        let score = priority + hits;
        if (data.lexical) {
          routed = true;
          const mask = data.lexical.length * 8 - 1;
          const matches = key => {
            const first = key & mask, second = (key >>> 15) & mask;
            return (data.lexical[first >>> 3] & (1 << (first & 7))) &&
              (data.lexical[second >>> 3] & (1 << (second & 7)));
          };
          const exactMatch = primaryHits === primary.length && exact.some(matches);
          let conceptMatch = 0;
          for (const concept of concepts) {
            if (matches(concept.signature) && routeHits(data.bloom, concept.terms) === concept.terms.length) {
              conceptMatch = Math.max(conceptMatch, concept.specificity);
            }
          }
          titlePriority = ((exactMatch ? 3 : 0) + conceptMatch) * data.titleConfidence;
          const pairStrength = pairs.filter(matches).length;
          let affinity = 0;
          if (query.vector && !query.emergency && !discussion && data.centroids)
            for (let offset = 0; offset < data.centroids.length; offset += 32)
              affinity = Math.max(affinity, vectorScore(query.vector, data.centroids.subarray(offset, offset + 32), true));
          const small = part.bytes < 200_000;
          score = 6 * priority + 3.5 * primaryHits / query.query.length +
            (exactMatch ? 14 : 0) + (conceptMatch ? 10 : 0) + 2.5 * Math.log1p(pairStrength) +
            12 * Math.max(0, affinity - 0.17) + (asset.format === 'pdf' ? 3 : 0) +
            (asset.critical ? 1 : 0) + (small ? 1 : 0) - (discussion && semanticPart(part) ? 1 : discussion ? 4 : 0);
        }
        const heuristic = score;
        if (evidence) {
          const lexical = impactPriority(evidence, part.impact, query);
          score = score * 0.65 + lexical;
          if (!semanticPart(part) && asset.format === 'zim' && hits > 1) score += 0.7;
        }
        sourceQueue.push({asset, number, hits, priority, score, heuristic,
          completeTerms: primaryHits === primary.length, titlePriority});
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
      const exact = queue.filter(item => item.titlePriority)
        .sort((a, b) => b.titlePriority - a.titlePriority || b.score - a.score);
      const titles = budget * 0.17;
      available = available - titles + add(exact, titles);
      const small = queue.filter(({asset, number}) =>
        (asset.format !== 'zim' || asset.parts.length <= 4) && semanticPart(asset.parts[number]));
      const reference = budget * 0.20;
      const short = small.filter(({asset, number, completeTerms}) =>
        completeTerms && asset.parts[number].bytes <= 38_000);
      available = available - reference + add(small, add(short, reference));
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

  const selectionBytes = new WeakMap();
  function completionBudget(selection, query) {
    if (query.emergency) return EMERGENCY_BYTES;
    let bytes = selectionBytes.get(selection.sources);
    if (bytes === undefined) {
      const parts = new Map();
      for (const asset of selection.sources)
        for (const [number, part] of asset.parts.entries())
          parts.set(partAddress(asset, number), part.bytes || 200_000);
      bytes = [...parts.values()].reduce((total, size) => total + size, 0);
      selectionBytes.set(selection.sources, bytes);
    }
    return bytes > COMPACT_INDEX ? BOUNDED_BYTES : COMPACT_BYTES;
  }

  function readChunk(readPart, asset, number, queryTerms) {
    const part = asset.parts[number];
    return readPart(part.pool || asset.sha256, part.number ?? number, queryTerms, part.path);
  }

  async function exactPass(selection, readPart, text, ids, limit, cancelled, domain, emergencySource) {
    const query = prepareQuery(text);
    if (!query.query.length || cancelled()) return [];
    const lookups = [query.query, ...query.evidence].map(phrase => phrase.map(hashTerm));
    const queryTerms = lookupTerms(query);
    const matches = [];
    for (const asset of selection.sources) {
      if (asset.legacy || ids && !ids.has(asset.id) || domain && !emergencySource(asset, domain)) continue;
      for (const [number, part] of asset.parts.entries()) {
        if (cancelled()) return [];
        const bloom = atob(part.bloom);
        if (!lookups.some(keys => routeHits(bloom, keys) === keys.length)) continue;
        const chunk = await readChunk(readPart, asset, number, queryTerms);
        if (cancelled()) return [];
        const hits = rankPart(chunk, query, asset, limit, true);
        if (!hits.length) continue;
        matches.push(...hits.map(hit => result(asset, hit, number)));
        retainCandidates(matches, limit * 4);
      }
    }
    return topResults(matches, limit);
  }

  async function lexicalPreview(selection, query, shelf, limit, readPart, queryTerms, cached, cancelled, onProgress) {
    const queue = rankedQueue(selection, query, shelf, PREVIEW_BYTES);
    for (const {asset, number} of queue) {
      if (cancelled()) return;
      const address = partAddress(asset, number);
      let chunk = cached.get(address);
      if (!chunk) {
        try {
          chunk = await readChunk(readPart, asset, number, queryTerms);
        } catch (_) {
          // A preview-only read can fail. Final ranking verifies its own reads.
          continue;
        }
        cached.set(address, chunk);
      }
      if (cancelled()) return;
      const hits = rankPart(chunk, query, asset, limit).map(hit => result(asset, hit, number));
      if (!hits.length) continue;
      onProgress(topResults(hits, limit), 'indexed');
      return;
    }
  }

  async function search(selection, encodeQuery, readPart, text, shelf = 'all', limit = 30,
                        cancelled = () => false, onProgress, budget = Infinity, readImpact, complete = false) {
    const query = prepareQuery(text);
    if (!query.query.length || cancelled()) return [];
    const queryTerms = lookupTerms(query);
    const canRoute = readImpact && selection.impact;
    const shared = new Map();
    const [encode, evidence] = await Promise.all([
      encodeQuery,
      canRoute ? impactEvidence(query, selection.impact, readImpact) : null,
      complete && canRoute && onProgress ?
        lexicalPreview(selection, query, shelf, limit, readPart, queryTerms, shared, cancelled, onProgress) : null,
    ]);
    if (cancelled()) return [];
    query.vector = encode(query.vectorText);
    const finalBudget = complete ? completionBudget(selection, query) : Infinity;
    const allowance = Math.min(budget, finalBudget);
    const queue = rankedQueue(selection, query, shelf, allowance - (evidence?.readBytes || 0), evidence);
    const multiple = new Map();
    for (const {asset, number} of queue) {
      const key = partAddress(asset, number);
      multiple.set(key, (multiple.get(key) || 0) + 1);
    }
    const matches = [];
    let updatedAt = -Infinity;
    for (const {asset, number} of queue) {
      if (cancelled()) return [];
      const address = partAddress(asset, number);
      const chunk = shared.get(address) ?? await readChunk(readPart, asset, number, queryTerms);
      const left = multiple.get(address) - 1;
      multiple.set(address, left);
      if (left) shared.set(address, chunk);
      else shared.delete(address);
      if (cancelled()) return [];
      const hits = rankPart(chunk, query, asset, limit);
      if (!hits.length) continue;
      matches.push(...hits.map(hit => result(asset, hit, number)));
      retainCandidates(matches, limit * 4);
      if (onProgress && performance.now() - updatedAt >= 150) {
        onProgress(topResults(matches, limit), 'indexed');
        updatedAt = performance.now();
      }
    }
    return topResults(matches, limit);
  }

  const order = (a, b) => (b.titleMatch || 0) - (a.titleMatch || 0) || b.score - a.score ||
    (a.rankTitle || a.record.title).localeCompare(b.rankTitle || b.record.title, 'en') ||
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
    // Keep each callback type serial across searches, while allowing term
    // buckets and record reads to overlap.
    let partQueue = Promise.resolve(), impactQueue = Promise.resolve();
    const readPart = (digest, number, query, path) => {
      if (path && !/^chunks\/[a-f0-9]{64}\.js$/.test(path)) return Promise.reject(Error('Invalid search chunk path'));
      if (!/^[a-f0-9]{64}$/.test(digest) || !Number.isInteger(number) || number < 0 || number >= 100000)
        return Promise.reject(Error('Invalid search shard'));
      const task = partQueue.then(async () => {
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
      partQueue = task.catch(() => {});
      return task;
    };
    const cache = new Map();
    function readImpact(path) {
      if (!/^[a-f0-9]{2}\.js$/.test(path)) return Promise.reject(Error('Invalid term bucket'));
      if (cache.has(path)) return cache.get(path);
      const task = impactQueue.then(async () => {
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
      impactQueue = task.catch(() => {});
      cache.set(path, task);
      task.catch(() => { if (cache.get(path) === task) cache.delete(path); });
      if (cache.size > 24) cache.delete(cache.keys().next().value);
      return task;
    }
    const runQuery = (text, shelf, limit, cancelled, onProgress, lexicalOnly = false, budget = BOUNDED_BYTES) =>
      run(selection, lexicalOnly ? () => null : loadModel(), readPart, text, shelf, limit, cancelled, onProgress,
        budget, selection.impact ? readImpact : undefined, true);
    let vocabulary;
    const correct = selection.impact && ((text, cancelled) => {
      vocabulary ??= new Set([...table.vocab, ...rules.flatMap(rule => rule.phrases.flatMap(words))]);
      return correctSpelling(text, vocabulary, selection.impact, readImpact, cancelled);
    });
    return Object.assign(runQuery, {embed: async text => (await loadModel()).embed?.(text), correct,
      exact: (...options) => exactPass(selection, readPart, ...options)});
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

  function nearbyPassages(matches, strong, words, heading) {
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

  function readerSearch(script, selection, table, {categoryIds, emergencySource, mobile, loadReranker}) {
    const run = classic(script, selection, table, async (index, encode, read, query, scope, ...options) => {
      const {category, domain} = scope;
      if (domain) {
        const [limit, cancelled] = options;
        const sources = index.sources.filter(source =>
          (!scope.ids || scope.ids.has(source.id)) && emergencySource(source, domain));
        return search({...index, sources}, encode, read, query, 'all', limit, cancelled, undefined, 1_200_000);
      }
      const ids = category && await categoryIds(category);
      const scoped = ids ? {...index, sources: index.sources.filter(source => ids.has(source.id))} : index;
      return search(scoped, encode, read, query, 'all', ...options);
    });
    const indexed = (text, category, limit, cancelled, onProgress, spellingRetry, semantic) =>
      run(text, {category}, limit, cancelled, onProgress, !semantic,
        semantic ? BOUNDED_BYTES : spellingRetry ? SPELLING_RETRY_BYTES : READER_BYTES);
    const exact = (text, ids, limit, cancelled, domain) => run.exact(text, ids, limit, cancelled, domain, emergencySource);
    async function emergency(text, {ids, domain, nearby, allowExact, cancelled, select}) {
      const file = record => record.destination || record.href.split('#')[0];
      const used = new Set(nearby.map(file));
      if (used.size === 3) return [];
      try {
        const hits = await run(text, {ids, domain}, 18, cancelled, undefined, true);
        if (cancelled()) return [];
        const passages = select(hits.filter(hit => hit.bodyMatch), prepareQuery(text))
          .filter(({record}) => !used.has(file(record))).slice(0, 3 - used.size);
        return passages.length || used.size || !allowExact ? passages : await exact(text, ids, 3, cancelled, domain);
      } catch (_) {
        // Keep the installed guide available when the local index fails.
        return [];
      }
    }
    let reranker;
    async function rank(text, category, limit, cancelled, onProgress, spellingRetry, semantic) {
      if (!semantic || !selection.reranker || mobile) {
        return indexed(text, category, limit, cancelled, onProgress, spellingRetry, semantic);
      }
      const all = await indexed(text, category, Math.max(limit, 50), cancelled,
        (hits, scope) => onProgress(hits.slice(0, limit), scope), spellingRetry, semantic);
      const initial = all.slice(0, limit);
      if (cancelled() || initial.length < 2 || initial[0].titleMatch || spellingRetry) return initial;
      onProgress(initial, 'ranked');
      try {
        reranker ??= loadReranker();
        const rerank = await reranker;
        const head = all.slice(0, 3);
        const shortlist = all.slice(3, 53);
        const rescored = await rerank(text, shortlist, cancelled);
        const remaining = [...rescored, ...all.slice(head.length + shortlist.length)];
        return cancelled() ? [] : [...head, ...topResults(remaining, limit - head.length)];
      } catch (_) {
        reranker = undefined;
        return initial;
      }
    }
    async function query(text, {category, ids, urgent, cancelled, spellingRetry, display, displayExact,
      applyCorrection, tryEmergency}) {
      const intent = prepareQuery(text);
      let rankedText = text;
      if (!intent.emergency && urgent?.keywords.includes('wound')) rankedText += ' wound care';
      if (!intent.emergency && urgent?.keywords.includes('scald')) rankedText += ' burn treatment';
      if (!intent.deliveryQuery && !intent.postpartum && urgent?.keywords.includes('childbirth')) rankedText += ' childbirth';
      const progress = (hits, phase) => { if (!cancelled()) display(hits, intent, phase); };
      const hits = await rank(rankedText, category, 85, cancelled, progress, spellingRetry);
      if (cancelled()) return false;
      const show = () => display(hits, intent) || displayExact(hits.filter(hit => hit.literalMatch));
      let count = show();
      const onlyRedirects = hits.length > 0 && hits.every(hit => hit.redirect || !hit.fullMatch);
      if ((!count || onlyRedirects) && !spellingRetry && run.correct) {
        const suggestion = await run.correct(text, cancelled);
        if (cancelled()) return false;
        if (suggestion && await applyCorrection(suggestion)) return true;
        if (cancelled()) return false;
        if (suggestion) count = show();
      }
      if (!count) {
        const matches = await exact(text, ids, 85, cancelled);
        if (cancelled()) return false;
        count = displayExact(matches);
      }
      if (!count && tryEmergency && !spellingRetry) {
        if (await tryEmergency()) return true;
        if (cancelled()) return false;
        const matches = await rank(rankedText, category, 85, cancelled, progress, false, true);
        if (!cancelled()) display(matches, intent);
      }
      return false;
    }
    return {query, emergency, embed: run.embed, navigationLocations};
  }

  // BEGIN GENERATED NAVIGATION SECTIONS
  const navigationSections = [
    ["Finding direction by the stars",[["survival_shelter",165,"Finding direction by the stars"],["survival_shelter",166,"Finding south by the Southern Cross and making an improvised compass"]],[["north|cardinal directions?|which direction","(?:cant|cannot|without).{0,30}(?:sun|sunlight)|no sun|at night|after dark"]]],
    ["Finding direction without a compass",[["survival_shelter",162,"Finding direction by the shadow-tip method"],["survival_shelter",165,"Finding direction by the stars"]],[["north|directions?|way|navigat\\w*","(?:without|dont have|do not have|no|lost (?:my|our|the)) (?:a |my |our )?compass"]]],
    ["Taking a bearing with a map and compass",[["navigation",2,"Taking a bearing with a map and compass"]],["map and compass",["bearings?|azimuth|magnetic declination","maps?|compass|north"]]],
    ["Reading contour lines on a topographic map",[["navigation",1,"Reading contour lines on a topographic map"]],[["contour (?:lines?|spacing)|contours","maps?|topographic|closely spaced|steep"]]],
  ];
  // END GENERATED NAVIGATION SECTIONS
  const navigationRoutes = navigationSections.map(([title, locations, aliases]) => ({
    name: normalize(title), locations, aliases: aliases.map(group => [group].flat()
      .map(value => new RegExp('\\b(?:' + value + ')\\b', 'u'))),
  }));

  function navigationLocations(phrase) {
    return navigationRoutes.filter(route => route.name === phrase ||
      route.aliases.some(group => group.every(pattern => pattern.test(phrase)))).flatMap(route => route.locations);
  }

  const api = {classic, readerSearch, model, binaryQuery, bytes, search, terms, prepareQuery, unpack, rankPart, normalize, result,
    retainCandidates, topResults, mergeRanked, nearbyPassages, lookupTerms, filter, vectorScore, placeholderTitle, displayTitle,
    emergencyMatches, navigationLocations,
    hashTerm, pairHash, rankedQueue, impactPostings, impactBlock, impactEvidence, correctSpelling,
    readBudget: READ_BUDGET, boundedBytes: BOUNDED_BYTES, completionBudget};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.OWLShardRank = api;
})(globalThis);
