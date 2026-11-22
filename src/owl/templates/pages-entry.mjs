import "./selector.js";
import "./selector-map.js";
import {mount} from "./builder-ui.mjs";

try {
  await mount();
} catch (error) {
  const notice = document.getElementById("fatal");
  notice.textContent = error.message;
  notice.hidden = false;
}
