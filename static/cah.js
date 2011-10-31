/*
 * Copyright (c) 2011 Google Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may
 * not use this file except in compliance with the License. You may obtain
 * a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
 * WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
 * License for the specific language governing permissions and limitations under
 * the License.
 */

/**
 * @fileoverview Logic for the Cards Against Hangouts app.
 *
 * @author Amy Unruh    (Google)
 * @author Brett Morgan (Google)
 * @author Nick Johnson (Google)
 */

/**
 * Shared state of the app.
 * @type {Object.<!string, !string>}
 * @private
 */
var state_ = null;

/**
 * Describes the shared state of the object.
 * @type {Object.<!string, Object.<!string, *>>}
 * @private
 */
var metadata_ = null;

/**
 * A list of the participants.
 * @type {Array.<gapi.hangout.Participant>}
 * @private
 */
var participants_ = null;

/**
 * Indicator the Channel API is open
 * @type {boolean}
 * @private
 */
var connected = false;

/**
 * Create required DOM elements and listeners.
 */
function prepareAppDOM() {
  // TODO(brettmorgan): do something
}

/**
 * Renders the app.
 */
function render() {
  // TODO(brettmorgan): do something
}

/**
 * Syncs local copies of shared state with those on the server and renders the
 *     app to reflect the changes.
 * @param {!Array.<Object.<!string, *>>} add Entries added to the shared state.
 * @param {!Array.<!string>} remove Entries removed from the shared state.
 * @param {!Object.<!string, !string>} state The shared state.
 * @param {!Object.<!string, Object.<!string, *>>} metadata Data describing the
 *     shared state.
 */
function onStateChanged(add, remove, state, metadata) {
  state_ = state;
  metadata_ = metadata;
  render();
}

/**
 * Syncs local copy of the participants list with that on the server and renders
 *     the app to reflect the changes.
 * @param {!Array.<gapi.hangout.Participant>} participants The new list of
 *     participants.
 */
function onParticipantsChanged(participants) {
  participants_ = participants;
  render();
}

// channel api management
function onOpened() {
  connected = true;
  window.alert('connected to server');
}

// placeholder - handling a message from the channel
function onMessage(m) {
  var newMessage, result_string;
  window.alert('received message:' + m.data);

  // TODO(brettmorgan): include json2 for older browsers
  newMessage = JSON.parse(m.data);

  // TODO(brettmorgan): fix with real channel message structure
  result_string = newMessage.content;

  document.getElementById('channel_message').innerHTML = result_string;
}

/**
 * Opens a Channel.
 * @param {string} token
 */
function openChannel(token) {
  var channel, handler, socket;

  channel = new goog.appengine.Channel(token);
  handler = {
    'onopen': onOpened,
    'onmessage': onMessage,
    'onerror': function () {},
    'onclose': function () {}
  };
  socket = channel.open(handler);
  socket.onopen = onOpened;
  socket.onmessage = onMessage;
}

/**
 * Get a game token, by joining a game.
 */
function getToken() {
  var hangout_id, user_hangout_id, plus_id, ajax_data;

  hangout_id = gapi.hangout.getHangoutId();
  // temp testing
  user_hangout_id = gapi.hangout.getParticipantId();
  plus_id = gapi.hangout.getParticipantById(user_hangout_id).id;
  alert("hanout_id = " + hanout_id + ", user_hangout_id = " + user_hangout_id + ", plus_id = " + plus_id);
  ajax_data = {
    hangout_id: "12345",
    plus_id: plus_id
  };

  $.ajax({
    url: "http://cah-xhack.appspot.com/api/join_game",
    success: function (data) {
      openChannel(data.channel_token);
    },
    data: ajax_data
  });
}


(function () {
  if (gapi && gapi.hangout) {

    var initHangout = function () {
      var initState, initMetadata, added, key, removed, initParticipants;

      prepareAppDOM();

      gapi.hangout.data.addStateChangeListener(onStateChanged);
      gapi.hangout.addParticipantsListener(onParticipantsChanged);

      if (!state_) {
        initState = gapi.hangout.data.getState();
        initMetadata = gapi.hangout.data.getStateMetadata();
        added = [];

        for (key in initMetadata) {
          if (initMetadata.hasOwnProperty(key)) {
            added.push(initMetadata[key]);
          }
        }
        removed = [];
        if (initState && initMetadata) {
          onStateChanged(added, removed, initState, initMetadata);
        }
      }
      if (!participants_) {
        initParticipants = gapi.hangout.getParticipants();
        if (initParticipants) {
          onParticipantsChanged(initParticipants);
        }
      }
      // var hid = gapi.hangout.getHangoutId();
      // var pid = gapi.hangout.getParticipantId();
      // alert("hangout and p id try 1: " + hid + " " + pid);

      getToken();

      gapi.hangout.removeApiReadyListener(initHangout);
    };

    gapi.hangout.addApiReadyListener(initHangout);
  }
}());

/*jslint browser: true, unparam: true, sloppy: true, nomen: true, maxlen: 100, indent: 2 */
